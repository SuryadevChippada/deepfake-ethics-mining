"""S4 - keyword-based candidate extraction (RQ1 stated values, RQ2 safeguards, RQ3 gender) + git history.

Everything here is a CANDIDATE for human coding, not a finding.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

import pandas as pd
from rich.progress import track

from . import cfg, console, data, need, out, read_json, slug
from .codebook import (CODES_BY_ID, DATA_DEMOGRAPHICS_STRONG, ETHICS_STATEMENT_CODES, GENDER, GENDERED_HARM_STRONG,
                       SAFEGUARD_CLAIM_PATTERNS, SAFEGUARD_HISTORY_KEYWORDS, SAFEGUARDS, STATED, compile_patterns, framing_hint,
                       issue_category_hint, repo_level_columns)
from .s3_collect import git, is_doc

CODE_EXTS = {".py", ".js", ".ts", ".ipynb", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".sh", ".bat"}
SRC_SPECS = ["*.py", "*.js", "*.ts", "*.yaml", "*.yml", "*.toml", "*.ini", "*.cfg"]
NOT_STATEMENT = re.compile(r"^(LICEN[CS]E|COPYING|CODE_OF_CONDUCT)|/CODE_OF_CONDUCT", re.I)
MAX_LINE = 400
LICENSE_LINE = re.compile(r"without restriction|permission is hereby granted|without warranty|merchantability|"
                          r"licensed under|license(d)? (as|to)|copyright \(c\)", re.I)


# ------------------------------------------------------------------ default-status parsing (RQ2)
NEGATIVE_NAME = re.compile(r"(^|[_\-])(no|skip|disable|disabled|without|off|bypass|ignore|unsafe|allow|remove|unlock)"
                           r"([_\-]|$)|^no[a-z]", re.I)
TRUE_STR = {"true", "1", "yes", "on", "y"}
FALSE_STR = {"false", "0", "no", "off", "n", "none", "null", ""}


def _bool(tok: str) -> bool | None:
    t = tok.strip().strip("'\"").lower()
    return True if t in TRUE_STR else False if t in FALSE_STR else None


def parse_default(stmt: str) -> tuple[str, str] | None:
    """Infer (status, mechanism) of a safeguard switch from one code statement.

    status: on | off | optional. `optional` = enabled by default but a user-facing switch can disable it.
    Returns None if no default can be read.
    """
    m = re.search(r"add_argument\(\s*['\"](-{0,2}[\w\-]+)['\"](?:\s*,\s*['\"](-{1,2}[\w\-]+)['\"])?", stmt)
    if m:
        name = (m.group(2) or m.group(1)).lstrip("-")
        val: bool | None = None
        if re.search(r"action\s*=\s*['\"]store_true['\"]", stmt):
            val = False
        elif re.search(r"action\s*=\s*['\"]store_false['\"]", stmt):
            val = True
        else:
            d = re.search(r"default\s*=\s*([^,)\s]+)", stmt)
            val = _bool(d.group(1)) if d else False if "required" not in stmt else None
        if val is None:
            return None
        on = (not val) if NEGATIVE_NAME.search(name) else val
        return ("optional" if on else "off"), "argparse"
    m = re.search(r"Checkbox\(.*?value\s*=\s*(True|False)", stmt)
    if m:
        on = m.group(1) == "True"
        neg = bool(re.search(r"label\s*=\s*['\"][^'\"]*\b(disable|skip|allow|bypass|no)\b", stmt, re.I))
        on = (not on) if neg else on
        return ("optional" if on else "off"), "ui_checkbox"
    m = re.search(r"(?:environ\.get|getenv)\(\s*['\"](\w+)['\"]\s*,\s*['\"]?([\w]*)['\"]?\s*\)", stmt)
    if m and _bool(m.group(2)) is not None:
        on = _bool(m.group(2))
        on = (not on) if NEGATIVE_NAME.search(m.group(1)) else on
        return ("optional" if on else "off"), "env_var"
    m = re.search(r"def\s+\w+\(.*?(\w+)\s*(?::\s*[\w\[\], .]+)?=\s*(True|False|None)", stmt)
    if m:
        on = m.group(2) == "True"
        on = (not on) if NEGATIVE_NAME.search(m.group(1)) else on
        return ("on" if on else "off"), "function_default"
    m = re.search(r"^\s*['\"]?([\w\-.]+)['\"]?\s*[:=]\s*['\"]?(true|false|True|False|yes|no|on|off|0|1)['\"]?\s*,?\s*(#.*)?$",
                  stmt)
    if m:
        on = _bool(m.group(2))
        on = (not on) if NEGATIVE_NAME.search(m.group(1)) else on
        return ("optional" if on else "off"), "config"
    return None


def aggregate_status(statuses: list[str | None]) -> str:
    """Repo-level default status from per-hit statuses."""
    s = {x for x in statuses if x}
    if not s:
        return "unclear"
    if s == {"on"}:
        return "on"
    if s == {"off"}:
        return "off"
    if "off" in s and s & {"on", "optional"}:
        return "optional"
    return "optional"


def statement_at(lines: list[str], i: int) -> str:
    """The (possibly multi-line) statement around line i: argparse calls are joined until parens balance."""
    start = i
    for j in range(i, max(i - 4, -1), -1):
        if "add_argument(" in lines[j] or "Checkbox(" in lines[j]:
            start = j
            break
    buf, depth = [], 0
    for line in lines[start: start + 10]:
        buf.append(line.strip())
        depth += line.count("(") - line.count(")")
        if depth <= 0 and len(buf) >= i - start + 1:
            break
    return " ".join(buf)


# ------------------------------------------------------------------ helpers
def sentence_of(line: str, match_start: int) -> str:
    parts, pos = re.split(r"(?<=[.!?])\s+", line), 0
    for p in parts:
        if pos + len(p) >= match_start:
            return p.strip()[:MAX_LINE]
        pos += len(p) + 1
    return line.strip()[:MAX_LINE]


def quote_window(text: str, start: int, max_words: int) -> str:
    words_before = text[:start].split()[-(max_words // 2):]
    words_after = text[start:].split()[: max_words - len(words_before)]
    return " ".join(words_before + words_after)


def blob_link(full: str, sha: str, path: str, line: int) -> str:
    return f"https://github.com/{full}/blob/{sha}/{quote(path)}#L{line}"


def git_dates(d: Path, regex: str, paths: list[str], literal: bool = False) -> list[str]:
    """Author dates (ISO, oldest first) of commits whose diff adds/removes a line matching `regex`. No e-mails."""
    if not paths:
        return []
    args = ["--literal-pathspecs"] if literal else []
    res = git(d, *args, "log", "-i", "-G", regex, "--format=%aI", "--reverse", "HEAD", "--", *paths, check=False)
    return [ln for ln in res.splitlines() if ln]


def ere_escape(s: str) -> str:
    return re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", s)


# ------------------------------------------------------------------ per repo
def extract_repo(full: str, sample_row: dict) -> dict:
    c = cfg()["extract"]
    ctx_n, cap = c["context_lines"], c["max_candidates_per_repo_code"]
    d, raw = data("repos", slug(full)), data("raw", slug(full), "x").parent
    meta = read_json(raw / "metadata.json")
    files, sha = read_json(raw / "files.json"), meta["head_sha"]
    cands: list[dict] = []
    counts: Counter = Counter()
    sg_status: dict[str, list[str | None]] = defaultdict(list)
    doc_hit_files: dict[str, set[str]] = defaultdict(set)
    doc_kw: dict[str, set[str]] = defaultdict(set)
    strong = {"harm": compile_patterns(GENDERED_HARM_STRONG), "demo": compile_patterns(DATA_DEMOGRAPHICS_STRONG)}
    flags = Counter()

    def add(**kw) -> None:
        key = (kw["code"], kw["source_type"])
        counts[key] += 1
        if counts[key] <= cap:
            cands.append({"repo": full, **kw})

    claims = [replace(s, patterns=SAFEGUARD_CLAIM_PATTERNS[s.id]) for s in SAFEGUARDS]
    doc_codes = STATED + [CODES_BY_ID["GENDERED_HARM"], CODES_BY_ID["DATA_DEMOGRAPHICS"]] + claims
    code_codes = SAFEGUARDS + [CODES_BY_ID["GENDER_FEATURE"]]

    # ---- documents (repo docs + HF cards)
    docs = [(p, (d / p), blob_link) for p in files if is_doc(p) and not NOT_STATEMENT.search(p)]
    docs += [(f"hf:{p.stem.replace('__', '/')}", p, None) for p in sorted((raw / "hf").glob("*.md"))]
    for path, fp, _ in docs:
        if not fp.exists():
            continue
        lines = fp.read_text(errors="replace").splitlines()
        src = "hf_card" if path.startswith("hf:") else "doc"
        for i, line in enumerate(lines):
            if len(line) > 5000:
                continue
            for code in doc_codes:
                ms = list(compile_patterns(code.patterns).finditer(line))
                if not ms:
                    continue
                sent = sentence_of(line, ms[0].start())
                rq = "RQ2_claim" if code in claims else code.rq
                if code.id == "GENDERED_HARM" and strong["harm"].search(line):
                    flags["gendered_harm_strong"] += 1
                if code.id == "DATA_DEMOGRAPHICS" and strong["demo"].search(line):
                    flags["data_demo_strong"] += 1
                if src == "doc":
                    doc_hit_files[code.id].add(path)
                    doc_kw[code.id].update(m.group(0).lower() for m in ms)
                link = (blob_link(full, sha, path, i + 1) if src == "doc"
                        else f"https://huggingface.co/{path[3:]}")
                add(rq=rq, code=code.id, source_type=src, file=path, line=i + 1,
                    match=";".join(sorted({m.group(0).lower() for m in ms})), sentence=sent,
                    context="\n".join(l[:MAX_LINE] for l in lines[max(0, i - ctx_n): i + ctx_n + 1]), link=link,
                    framing_hint=framing_hint(sent) if code in STATED else "", default_hint="", category_hint="")

    # ---- source / config
    for path in files:
        if Path(path).suffix.lower() not in CODE_EXTS or not (d / path).exists():
            continue
        lines = (d / path).read_text(errors="replace").splitlines()
        for i, line in enumerate(lines):
            if len(line) > MAX_LINE * 3 or LICENSE_LINE.search(line):
                continue
            for code in code_codes:
                ms = list(compile_patterns(code.patterns).finditer(line))
                if not ms:
                    continue
                dflt = ""
                if code in SAFEGUARDS:
                    pd_ = parse_default(statement_at(lines, i))
                    dflt = f"{pd_[0]} ({pd_[1]})" if pd_ else "unclear"
                    sg_status[code.id].append(pd_[0] if pd_ else None)
                add(rq=code.rq, code=code.id, source_type="code", file=path, line=i + 1,
                    match=";".join(sorted({m.group(0).lower() for m in ms})), sentence=line.strip()[:MAX_LINE],
                    context="\n".join(l[:MAX_LINE] for l in lines[max(0, i - ctx_n): i + ctx_n + 1]),
                    link=blob_link(full, sha, path, i + 1), framing_hint="", default_hint=dflt, category_hint="")

    # ---- issues / PRs / comments (RQ3)
    ig = compile_patterns(CODES_BY_ID["ISSUE_GENDER"].patterns)
    issue_cats: Counter = Counter()
    issues, comments = read_json(raw / "issues.json", []), read_json(raw / "comments.json", [])
    texts = [("pr" if i["is_pr"] else "issue", f"{i['title']}\n{i['body']}", i) for i in issues]
    texts += [("comment", cm["body"], cm) for cm in comments]
    for src, text, it in texts:
        m = ig.search(text)
        if not m:
            continue
        cat = issue_category_hint(text)
        issue_cats[cat] += 1
        add(rq="RQ3", code="ISSUE_GENDER", source_type=src, file=f"#{it.get('number', it.get('issue_number'))}",
            line=None, match=";".join(sorted({x.group(0).lower() for x in ig.finditer(text)}))[:200],
            sentence=quote_window(text.replace("\n", " "), m.start(), c["quote_max_words"]), context="",
            link=it["url"], framing_hint="", default_hint="", category_hint=cat,
            author=it["author"], author_role=it["author_role"], created_at=it["created_at"])

    # ---- history: first appearance of stated values (RQ1)
    timeline = []
    readme = next((p for p in files if re.fullmatch(r"README(\.\w+)?", p, re.I)), None)
    readme_first = (git_dates(d, ".", [readme], literal=True) or [None])[0] if readme else None
    for code in STATED:
        if not doc_hit_files.get(code.id):
            continue
        rx = "|".join(ere_escape(k) for k in sorted(doc_kw[code.id])[:15])
        dates = git_dates(d, rx, sorted(doc_hit_files[code.id]), literal=True)
        row = {"repo": full, "code": code.id, "first_date": dates[0] if dates else None,
               "files": ";".join(sorted(doc_hit_files[code.id])), "created_at": meta["created_at"],
               "readme_first_commit": readme_first}
        for ev in c["events"]:
            row[f"after_{ev['id']}"] = bool(row["first_date"] and row["first_date"][:10] > ev["date"])
        timeline.append(row)

    # ---- safeguards: status, history, stated-vs-enacted
    sg_rows, contradictions = [], []
    for sg in SAFEGUARDS:
        n_code = counts[(sg.id, "code")]
        claimed = counts[(sg.id, "doc")] + counts[(sg.id, "hf_card")]
        hist = git_dates(d, SAFEGUARD_HISTORY_KEYWORDS[sg.id], SRC_SPECS)
        dflt_changes = git_dates(d, f"({SAFEGUARD_HISTORY_KEYWORDS[sg.id]}).*(default|store_true|store_false|True|False)",
                                 SRC_SPECS)
        status = aggregate_status(sg_status[sg.id]) if n_code else "NA"
        sg_rows.append({"repo": full, "safeguard": sg.id, "enacted": n_code > 0, "code_hits": n_code,
                        "default_status": status, "claimed_in_docs": claimed > 0, "doc_hits": claimed,
                        "added_date": hist[0] if hist else None,
                        "removed_date": hist[-1] if hist and not n_code else None,
                        "default_change_dates": ";".join(dflt_changes[-5:])})
        claim = next((x for x in cands if x["code"] == sg.id and x["source_type"] in ("doc", "hf_card")), None)
        code_ev = next((x for x in cands if x["code"] == sg.id and x["source_type"] == "code"), None)
        kind = ("claimed_not_found_in_code" if claimed and not n_code
                else "claimed_but_default_off" if claimed and status == "off" else None)
        if kind:
            contradictions.append({"repo": full, "safeguard": sg.id, "type": kind,
                                   "readme_claim": claim["sentence"] if claim else "", "claim_link": claim["link"] if claim else "",
                                   "code_evidence": code_ev["sentence"] if code_ev else "",
                                   "code_link": code_ev["link"] if code_ev else ""})

    # ---- automatic repo-level codes (PRELIMINARY)
    feat = {"repo": full}
    for code in STATED:
        feat[f"stated_{code.id}"] = "yes" if counts[(code.id, "doc")] + counts[(code.id, "hf_card")] else "no"
    for r in sg_rows:
        feat[f"enacted_{r['safeguard']}"] = "yes" if r["enacted"] else "no"
        feat[f"default_{r['safeguard']}"] = r["default_status"]
    feat["gendered_harm_ack"] = "yes" if flags["gendered_harm_strong"] else "no"
    feat["data_demographics_documented"] = "yes" if flags["data_demo_strong"] else "no"
    feat["gender_as_feature"] = "yes" if counts[("GENDER_FEATURE", "code")] else "no"
    for (code, src), n in counts.items():
        feat[f"n_{code}_{src}"] = n
    for cat, n in issue_cats.items():
        feat[f"issues_{cat}"] = n
    frames = Counter(x["framing_hint"] for x in cands if x["rq"] == "RQ1")
    for f, n in frames.items():
        feat[f"framing_{f}"] = n
    feat["n_issues_scanned"] = len(issues)
    feat["n_comments_scanned"] = len(comments)
    feat["readme_first_commit"] = readme_first
    return {"cands": cands, "feat": feat, "timeline": timeline, "sg": sg_rows, "contra": contradictions,
            "counts": counts}


# ------------------------------------------------------------------ evidence markdown
def evidence_md(full: str, res: dict, srow: dict) -> str:
    L = [f"# Evidence: {full}", "", f"> PRELIMINARY – automatic keyword candidates, unverified. Type: {srow['type']}, "
         f"coder: {srow['coder']}{' + overlap' if srow['overlap'] else ''}.", ""]
    by = defaultdict(list)
    for cnd in res["cands"]:
        by[(cnd["rq"], cnd["code"])].append(cnd)
    for (rq, code), items in sorted(by.items()):
        total = sum(n for (cd, _), n in res["counts"].items() if cd == code)
        L += [f"## {rq} · {code} ({len(items)} shown / {total} hits)", ""]
        for x in items:
            loc = f"{x['file']}:{x['line']}" if x["line"] else x["file"]
            hint = " · ".join(h for h in (x["framing_hint"], x["default_hint"], x["category_hint"]) if h)
            L.append(f"- [{loc}]({x['link']}) `{x['match']}`{' — ' + hint if hint else ''}  ")
            L.append(f"  > {x['sentence'].replace(chr(10), ' ')[:300]}")
        L.append("")
    L += ["## Safeguard summary", "", pd.DataFrame(res["sg"]).drop(columns="repo").to_markdown(index=False)
          if res["sg"] else "-", ""]
    if res["timeline"]:
        L += ["## RQ1 timeline", "", pd.DataFrame(res["timeline"]).drop(columns="repo").to_markdown(index=False), ""]
    return "\n".join(L)


# ------------------------------------------------------------------ stage
def run(refresh: bool = False, repo: str | None = None, **_) -> None:
    sample = pd.read_csv(need(out("s2_sample.csv"), "select"))
    log = pd.read_csv(need(out("s3_collection_log.csv"), "collect"))
    ok = set(log.loc[log["status"] == "ok", "full_name"])
    targets = [r for r in sample["full_name"] if r in ok and (not repo or r == repo)]
    rows = {r["full_name"]: r for r in sample.to_dict("records")}
    acc = defaultdict(list)
    with ThreadPoolExecutor(max_workers=6) as ex:   # git-bound, so threads parallelise well
        results = list(track(ex.map(lambda f: (f, extract_repo(f, rows[f])), targets), total=len(targets),
                             description="S4 extract"))
    for full, res in results:
        for cnd in res["cands"]:
            cnd.setdefault("author", "")
        acc["cands"] += res["cands"]
        acc["feat"].append(res["feat"])
        acc["timeline"] += res["timeline"]
        acc["sg"] += res["sg"]
        acc["contra"] += res["contra"]
        out("evidence", slug(full) + ".md").write_text(evidence_md(full, res, rows[full]))
    if repo:   # merge into existing outputs
        for key, fname in [("cands", "s4_candidates.csv"), ("feat", "s4_repo_features.csv"), ("timeline", "s4_timeline.csv"),
                           ("sg", "s4_safeguards.csv"), ("contra", "s4_contradictions.csv")]:
            p = out(fname)
            if p.exists():
                old = pd.read_csv(p)
                old = old[old["repo"] != repo] if "repo" in old else old
                acc[key] = old.to_dict("records") + acc[key]
    cands = pd.DataFrame(acc["cands"])
    cands.insert(0, "candidate_id", [f"C{i:05d}" for i in range(1, len(cands) + 1)])
    cands.to_csv(out("s4_candidates.csv"), index=False)
    feats = pd.DataFrame(acc["feat"])
    for col in repo_level_columns():
        if col not in feats:
            feats[col] = "no"
    feats.fillna(0).to_csv(out("s4_repo_features.csv"), index=False)
    pd.DataFrame(acc["timeline"]).to_csv(out("s4_timeline.csv"), index=False)
    pd.DataFrame(acc["sg"]).to_csv(out("s4_safeguards.csv"), index=False)
    pd.DataFrame(acc["contra"], columns=["repo", "safeguard", "type", "readme_claim", "claim_link", "code_evidence",
                                         "code_link"]).to_csv(out("s4_contradictions.csv"), index=False)
    console.print(f"[green]S4: {len(feats)} repos, {len(cands)} candidates "
                  f"({cands.groupby('rq').size().to_dict() if len(cands) else {}}), "
                  f"{len(acc['contra'])} stated-vs-enacted flags -> output/s4_*.csv, output/evidence/")
