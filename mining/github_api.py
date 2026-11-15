"""GitHub REST client: auth, on-disk cache, rate limiting, pagination."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Any, Iterator

import requests

from . import console, data

API = "https://api.github.com"
MAX_RETRIES = 6


def get_token() -> str | None:
    """Token from $GITHUB_TOKEN, else `gh auth token`. Never stored on disk by this code."""
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


class GitHub:
    """Cached GitHub client. Every response (incl. 404) is cached under data/cache/."""

    def __init__(self, refresh: bool = False) -> None:
        self.refresh = refresh
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                               "User-Agent": "msr-research-pipeline"})
        tok = get_token()
        if tok:
            self.s.headers["Authorization"] = f"Bearer {tok}"
        else:
            console.print("[yellow]No GitHub token (GITHUB_TOKEN or gh auth). Rate limits will be very low.")
        self.calls = 0

    # ---------------------------------------------------------------- core
    def _cache_path(self, url: str, params: dict | None, accept: str | None):
        key = json.dumps([url, sorted((params or {}).items()), accept])
        h = hashlib.sha256(key.encode()).hexdigest()
        return data("cache", h[:2], h + ".json")

    def request(self, url: str, params: dict | None = None, accept: str | None = None) -> dict[str, Any]:
        """GET with cache. Returns {"status", "json"|"text", "link"}."""
        if not url.startswith("http"):
            url = API + url
        cp = self._cache_path(url, params, accept)
        if cp.exists() and not self.refresh:
            return json.loads(cp.read_text())
        headers = {"Accept": accept} if accept else {}
        for attempt in range(MAX_RETRIES):
            try:
                r = self.s.get(url, params=params, headers=headers, timeout=60)
            except requests.RequestException as e:
                self._backoff(attempt, str(e))
                continue
            self.calls += 1
            if self._rate_limited(r):
                continue
            if r.status_code >= 500 or r.status_code == 202:   # 202: stats being computed
                self._backoff(attempt, f"HTTP {r.status_code}")
                continue
            res: dict[str, Any] = {"status": r.status_code, "link": r.headers.get("Link", "")}
            if "json" in r.headers.get("Content-Type", ""):
                res["json"] = r.json()
            else:
                res["text"] = r.text
            if r.status_code in (200, 404, 410, 451, 409, 403, 422):
                cp.write_text(json.dumps(res))
            return res
        raise RuntimeError(f"GitHub request failed after {MAX_RETRIES} retries: {url}")

    def _rate_limited(self, r: requests.Response) -> bool:
        """Sleep until reset if the (primary or secondary) limit is hit; True means retry."""
        remaining = r.headers.get("X-RateLimit-Remaining")
        limited = r.status_code in (403, 429) and (remaining == "0" or "rate limit" in r.text.lower())
        if not limited:
            if remaining is not None and int(remaining) <= 1:   # pre-emptive sleep before next call fails
                self._sleep_until(r)
            return False
        self._sleep_until(r)
        return True

    def _sleep_until(self, r: requests.Response) -> None:
        if r.headers.get("Retry-After"):
            wait = int(r.headers["Retry-After"]) + 1
        else:
            wait = max(int(r.headers.get("X-RateLimit-Reset", time.time() + 60)) - int(time.time()), 1) + 2
        console.print(f"[yellow]Rate limit ({r.headers.get('X-RateLimit-Resource', '?')}): sleeping {wait}s")
        time.sleep(wait)

    @staticmethod
    def _backoff(attempt: int, why: str) -> None:
        wait = min(2 ** attempt * 2, 120)
        console.print(f"[yellow]{why}: retry in {wait}s")
        time.sleep(wait)

    # ---------------------------------------------------------------- helpers
    def get_json(self, url: str, params: dict | None = None) -> Any:
        res = self.request(url, params)
        return res.get("json") if res["status"] == 200 else None

    def paginate(self, url: str, params: dict | None = None, max_items: int | None = None) -> Iterator[dict]:
        """Yield items across Link-header pages (list endpoints or search `items`)."""
        params = dict(params or {}, per_page=100)
        n, next_url = 0, url
        while next_url:
            res = self.request(next_url, params)
            if res["status"] != 200:
                return
            body = res.get("json")
            items = body.get("items", []) if isinstance(body, dict) else (body or [])
            for it in items:
                yield it
                n += 1
                if max_items and n >= max_items:
                    return
            m = re.search(r'<([^>]+)>;\s*rel="next"', res.get("link", ""))
            next_url, params = (m.group(1), None) if m else (None, None)

    def search_repos(self, q: str, max_items: int) -> tuple[int, list[dict]]:
        """Search repositories sorted by stars; returns (total_count, items)."""
        first = self.request("/search/repositories", {"q": q, "sort": "stars", "order": "desc", "per_page": 100})
        if first["status"] != 200:
            console.print(f"[red]Search failed ({first['status']}): {q}")
            return 0, []
        total = first["json"].get("total_count", 0)
        items = list(self.paginate("/search/repositories", {"q": q, "sort": "stars", "order": "desc"}, max_items))
        return total, items

    def search_count(self, q: str, kind: str = "issues") -> int | None:
        res = self.request(f"/search/{kind}", {"q": q, "per_page": 1})
        return res["json"].get("total_count") if res["status"] == 200 else None

    def readme(self, full_name: str) -> str | None:
        res = self.request(f"/repos/{full_name}/readme", accept="application/vnd.github.raw")
        if res["status"] != 200:
            return None
        return res.get("text") if "text" in res else json.dumps(res.get("json"))

    def count_via_link(self, url: str, params: dict | None = None) -> int:
        """Count list items cheaply with per_page=1 and the last-page number."""
        res = self.request(url, dict(params or {}, per_page=1))
        if res["status"] != 200:
            return 0
        m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', res.get("link", ""))
        return int(m.group(1)) if m else len(res.get("json") or [])
