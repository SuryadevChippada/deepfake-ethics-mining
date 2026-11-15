"""S1 - GitHub search and sampling frame."""
from __future__ import annotations

import pandas as pd
from rich.progress import track

from . import cfg, console, out, snapshot
from .github_api import GitHub

COLUMNS = ["id", "full_name", "url", "stars", "forks", "created_at", "pushed_at", "archived", "fork", "language",
           "license", "topics", "description", "matched_queries"]


def _row(it: dict) -> dict:
    return {
        "id": it["id"], "full_name": it["full_name"], "url": it["html_url"], "stars": it["stargazers_count"],
        "forks": it["forks_count"], "created_at": it["created_at"], "pushed_at": it["pushed_at"],
        "archived": it["archived"], "fork": it["fork"], "language": it.get("language") or "",
        "license": (it.get("license") or {}).get("spdx_id") or "", "topics": ";".join(it.get("topics") or []),
        "description": (it.get("description") or "").replace("\n", " "),
    }


def run(refresh: bool = False, **_) -> pd.DataFrame:
    c = cfg()["search"]
    snap = snapshot(refresh)
    gh = GitHub(refresh)
    rows: dict[int, dict] = {}
    matched: dict[int, set[str]] = {}
    qlog: list[dict] = []
    for q in track(c["queries"], description="S1 search"):
        base = f"{q} stars:>={c['min_stars']}"
        total, items = gh.search_repos(base, c["max_results_per_query"])
        if total > c["max_results_per_query"]:   # split by star ranges to get past the 1000 cap
            items = []
            for rng in c["star_ranges"]:
                items += gh.search_repos(f"{q} stars:{rng}", c["max_results_per_query"])[1]
        for it in items:
            rows[it["id"]] = _row(it)
            matched.setdefault(it["id"], set()).add(q)
        qlog.append({"query": base, "total_count": total, "fetched": len(items)})
        console.log(f"{q!r}: total={total}, fetched={len(items)}")
    pd.DataFrame(qlog).to_csv(out("s1_query_log.csv"), index=False)
    df = pd.DataFrame(rows.values(), columns=COLUMNS[:-1])
    df["matched_queries"] = df["id"].map(lambda i: " | ".join(sorted(matched[i])))
    df = df.sort_values("stars", ascending=False)
    df.to_csv(out("s1_candidates.csv"), index=False)
    console.print(f"[green]S1: {len(df)} unique candidates from {len(c['queries'])} queries "
                  f"(snapshot {snap['snapshot_utc']}) -> output/s1_candidates.csv")
    return df
