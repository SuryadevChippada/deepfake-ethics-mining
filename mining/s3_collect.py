"""S3 - collect metadata, text files (partial clone), issues/PRs, comments and HF model cards.

Safety: nothing from a mined repository is executed, imported or installed. Clones are blobless and
only text files <= max_file_bytes are checked out; LFS smudge and hooks are disabled.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path

import pandas as pd
import requests
from rich.progress import track

from . import cfg, console, data, need, out, pseudonymise, read_json, scrub, slug, write_json
from .codebook import ISSUE_CATEGORY_PATTERNS, CODES_BY_ID, compile_patterns
from .github_api import GitHub

GIT_ENV = {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0"}
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=never",
            "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=", "-c", "filter.lfs.required=false"]
MAINTAINER_ROLES = {"OWNER", "MEMBER", "COLLABORATOR"}
HF_RE = re.compile(r"huggingface\.co/(?!datasets/|spaces/|docs|blog|papers|models\b|join|login|settings|collections/)"
                   r"([A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*)")
# Issues whose comments are fetched: gender/sexual terms (RQ3) or ethics terms.
COMMENT_TRIGGER = CODES_BY_ID["ISSUE_GENDER"].patterns + ISSUE_CATEGORY_PATTERNS["ethical_concern"]


def git(repo_dir: Path, *args: str, stdin: str | None = None, check: bool = True) -> str:
    """Run git inside a mined clone with hooks/filters disabled."""
    r = subprocess.run(["git", *GIT_SAFE, "-C", str(repo_dir), *args], input=stdin, capture_output=True, text=True,
                       env=GIT_ENV, timeout=cfg()["collect"]["git_timeout_s"], errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout


def role(assoc: str | None) -> str:
    return "maintainer" if (assoc or "") in MAINTAINER_ROLES else "user"


def is_doc(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in cfg()["collect"]["doc_globs"])


def wanted(path: str, size: int) -> bool:
    c = cfg()["collect"]
    if size > c["max_file_bytes"] or any(part in c["skip_dirs"] for part in path.split("/")[:-1]):
        return False
    return is_doc(path) or Path(path).suffix.lower() in c["code_exts"]


# ------------------------------------------------------------------ clone
def batch_fetch(d: Path, oids: list[str]) -> None:
    """Fetch many blobs in one request (what git's promisor lazy-fetch does internally)."""
    if oids:
        git(d, "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "origin", "--no-tags", "--no-write-fetch-head",
            "--recurse-submodules=no", "--filter=blob:none", "--stdin", stdin="\n".join(oids), check=False)


def clone(full_name: str, refresh: bool, gh: GitHub) -> dict:
    """Blobless clone, checkout of wanted text files, history prefetch for text extensions."""
    c = cfg()["collect"]
    d = data("repos", slug(full_name))
    if refresh and d.exists():
        subprocess.run(["rm", "-rf", str(d)], check=True)
    if not (d / ".git").exists():
        subprocess.run(["git", *GIT_SAFE, "clone", "-q", "--filter=blob:none", "--no-checkout",
                        f"https://github.com/{full_name}.git", str(d)], check=True, env=GIT_ENV,
                       capture_output=True, timeout=c["git_timeout_s"])
    head = git(d, "rev-parse", "HEAD").strip()
    files, head_oids = [], []
    # Sizes from the trees API: `git ls-tree -l` would lazily fetch every blob of a blobless clone.
    tree = gh.get_json(f"/repos/{full_name}/git/trees/{head}", {"recursive": "1"}) or {}
    if tree.get("truncated"):
        console.print(f"[yellow]{full_name}: tree listing truncated by GitHub; some files skipped")
    for e in tree.get("tree", []):
        if e["type"] == "blob" and wanted(e["path"], e.get("size", 0)):
            files.append(e["path"])
            head_oids.append(e["sha"])
    if files:
        batch_fetch(d, head_oids)  # path-limited checkout would otherwise fetch blobs one by one
        git(d, "--literal-pathspecs", "checkout", "-q", "HEAD", "--pathspec-from-file=-", "--pathspec-file-nul",
            stdin="\0".join(files))
    # Prefetch every historical blob of text files in one batch so `git log -G/-S` runs offline.
    specs = [f"*{e}" for e in c["history_exts"]]
    oids = {ln.split()[3] for ln in git(d, "log", "--format=", "--raw", "--no-abbrev", "--no-renames", "HEAD", "--", *specs)
            .splitlines() if ln.startswith(":") and not set(ln.split()[3]) <= {"0"}}
    oids_l = sorted(oids)[: c["history_blob_cap"]]
    batch_fetch(d, oids_l)
    return {"head_sha": head, "files": files, "history_blobs": len(oids_l), "history_blobs_total": len(oids)}


# ------------------------------------------------------------------ issues
def collect_issues(gh: GitHub, full_name: str) -> tuple[list[dict], list[dict], bool]:
    c = cfg()["collect"]
    issues = []
    for it in gh.paginate(f"/repos/{full_name}/issues", {"state": "all", "sort": "created", "direction": "desc"},
                          c["issue_cap"]):
        issues.append({
            "number": it["number"], "is_pr": "pull_request" in it, "state": it["state"],
            "created_at": it["created_at"], "comments": it["comments"],
            "labels": ";".join(l["name"] for l in it.get("labels", [])),
            "title": scrub(it.get("title")), "body": scrub(it.get("body")),
            "author": pseudonymise((it.get("user") or {}).get("login")), "author_role": role(it.get("author_association")),
            "url": it["html_url"],
        })
    truncated = len(issues) >= c["issue_cap"]
    trig = compile_patterns(COMMENT_TRIGGER)
    hits = [i for i in issues if i["comments"] and trig.search(i["title"] + " " + i["body"])][: c["comment_issue_cap"]]
    comments = []
    for i in hits:
        for cm in gh.paginate(f"/repos/{full_name}/issues/{i['number']}/comments"):
            comments.append({"issue_number": i["number"], "created_at": cm["created_at"], "body": scrub(cm.get("body")),
                             "author": pseudonymise((cm.get("user") or {}).get("login")),
                             "author_role": role(cm.get("author_association")), "url": cm["html_url"]})
    return issues, comments, truncated


# ------------------------------------------------------------------ HF cards
def hf_cards(readme: str, dest: Path, refresh: bool) -> list[str]:
    """Fetch model-card text (README.md) for HF repos linked in the README. No weights, no auth header."""
    ids = list(dict.fromkeys(m.rstrip(".,)") for m in HF_RE.findall(readme)))[: cfg()["collect"]["hf_cards_max"]]
    got = []
    for mid in ids:
        p = dest / (mid.replace("/", "__") + ".md")
        if not p.exists() or refresh:
            try:
                r = requests.get(f"https://huggingface.co/{mid}/raw/main/README.md", timeout=30)
            except requests.RequestException:
                continue
            if r.status_code != 200 or "text" not in r.headers.get("Content-Type", "") or len(r.content) > 2_000_000:
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(r.text)
        got.append(mid)
    return got


# ------------------------------------------------------------------ stage
def run(refresh: bool = False, repo: str | None = None, **_) -> pd.DataFrame:
    sample = pd.read_csv(need(out("s2_sample.csv"), "select"))
    targets = [repo] if repo else list(sample["full_name"])
    gh = GitHub(refresh)
    log_path = out("s3_collection_log.csv")
    old = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(columns=["full_name"])
    log = {r["full_name"]: r for r in old.to_dict("records") if r["full_name"] in set(sample["full_name"])}
    for full in track(targets, description="S3 collect"):
        raw = data("raw", slug(full), "x").parent
        row: dict = {"full_name": full, "status": "ok", "error": ""}
        try:
            meta = gh.get_json(f"/repos/{full}") or {}
            if not meta:
                raise RuntimeError("repository metadata unavailable (deleted/blocked?)")
            m = {k: meta.get(k) for k in ("full_name", "html_url", "stargazers_count", "forks_count", "created_at",
                                          "pushed_at", "archived", "homepage", "default_branch", "open_issues_count",
                                          "topics", "description")}
            m["license"] = (meta.get("license") or {}).get("spdx_id")
            m["contributors"] = gh.count_via_link(f"/repos/{full}/contributors", {"anon": "1"})
            m["issues_open"] = gh.search_count(f"repo:{full} is:issue is:open")
            m["issues_closed"] = gh.search_count(f"repo:{full} is:issue is:closed")
            cl = clone(full, refresh, gh)
            m.update(head_sha=cl["head_sha"], history_blobs=cl["history_blobs"])
            write_json(raw / "metadata.json", m)
            write_json(raw / "files.json", cl["files"])
            issues_p = raw / "issues.json"
            if refresh or not issues_p.exists():
                issues, comments, trunc = collect_issues(gh, full)
                write_json(issues_p, issues)
                write_json(raw / "comments.json", comments)
                write_json(raw / "issues_meta.json", {"truncated": trunc, "cap": cfg()["collect"]["issue_cap"]})
            issues, comments = read_json(issues_p), read_json(raw / "comments.json", [])
            readme = gh.readme(full) or ""
            cards = hf_cards(readme, raw / "hf", refresh)
            row.update(head_sha=cl["head_sha"], files=len(cl["files"]), history_blobs=cl["history_blobs"],
                       issues=sum(not i["is_pr"] for i in issues), prs=sum(i["is_pr"] for i in issues),
                       comments=len(comments), issues_truncated=read_json(raw / "issues_meta.json")["truncated"],
                       hf_cards=len(cards), contributors=m["contributors"])
        except Exception as e:  # keep going; failure is logged per repo
            row.update(status="error", error=str(e)[:300])
            console.print(f"[red]{full}: {e}")
        log[full] = row
    df = pd.DataFrame(log.values())
    df.to_csv(log_path, index=False)
    ok = (df["status"] == "ok").sum()
    console.print(f"[green]S3: {ok}/{len(df)} repos collected; files={int(df.get('files', pd.Series()).fillna(0).sum())}, "
                  f"issues+PRs={int(df.get('issues', pd.Series()).fillna(0).sum() + df.get('prs', pd.Series()).fillna(0).sum())}"
                  f", comments={int(df.get('comments', pd.Series()).fillna(0).sum())} -> output/s3_collection_log.csv")
    return df
