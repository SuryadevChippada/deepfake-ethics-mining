"""S2 - inclusion/exclusion, tool-type classification, stratified selection, coder assignment."""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs
from rich.progress import track
from rich.table import Table

from . import cfg, console, need, out
from .github_api import GitHub

TYPES = ["face_swap", "talking_head_lipsync", "voice", "full_body_or_other"]
DetectorFactory.seed = 0


# ------------------------------------------------------------------ heuristics
def meta_text(r: pd.Series) -> str:
    return " ".join(str(r.get(k, "") or "") for k in ("full_name", "description", "topics")).replace(";", " ").lower()


def classify_type(text: str) -> str | None:
    """Tool type by keyword-count; generic terms ('deepfake') only when nothing specific matched."""
    c = cfg()["select"]
    scores = {t: sum(bool(re.search(p, text, re.I)) for p in c["type_keywords"][t]) for t in TYPES}
    best = max(TYPES, key=lambda t: scores[t])   # max() keeps first type on ties
    if scores[best]:
        return best
    for t, pats in c["generic_type_keywords"].items():
        if any(re.search(p, text, re.I) for p in pats):
            return t
    return None


def apply_rules(text: str) -> tuple[str | None, list[str]]:
    """Return (exclusion_rule_id or None, [flag rule ids]) for not-a-generation-tool rules."""
    c = cfg()["select"]
    is_gen = bool(re.search(c["generation_words"], text, re.I))
    flags: list[str] = []
    for rule in c["not_generation_rules"]:
        if not re.search(rule["pattern"], text, re.I) or (rule.get("unless_generation") and is_gen):
            continue
        if rule["action"] == "exclude":
            return rule["id"], flags
        flags.append(rule["id"])
    return None, flags


def clean_readme(md: str) -> str:
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"<[^>]+>|`[^`]*`|!\[[^\]]*\]\([^)]*\)|https?://\S+", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    return re.sub(r"[#*|>_\-=]+", " ", md)


def english_prob(md: str) -> float | None:
    """Probability that README prose is English (None if too little text)."""
    txt = clean_readme(md)
    if len(txt.strip()) < cfg()["select"]["readme_min_chars_for_langdetect"]:
        return None
    try:
        return next((l.prob for l in detect_langs(txt[:20000]) if l.lang == "en"), 0.0)
    except LangDetectException:
        return None


# ------------------------------------------------------------------ selection
def allocate(counts: dict[str, int], n: int, min_per: int) -> dict[str, int]:
    """Proportional allocation with a per-stratum minimum (capped by stratum size)."""
    total = sum(counts.values())
    if total <= n:
        return dict(counts)
    target = {t: n * c / total for t, c in counts.items()}
    floor = {t: min(min_per, c) for t, c in counts.items()}
    alloc = {t: min(c, max(floor[t], math.floor(target[t]))) for t, c in counts.items()}
    keys = sorted(counts)  # deterministic tie order
    while sum(alloc.values()) < n:
        t = max((k for k in keys if alloc[k] < counts[k]), key=lambda k: target[k] - alloc[k])
        alloc[t] += 1
    while sum(alloc.values()) > n:
        t = max((k for k in keys if alloc[k] > floor[k]), key=lambda k: alloc[k] - target[k])
        alloc[t] -= 1
    return alloc


def stratified_select(eligible: pd.DataFrame, n: int, min_per: int, seed: int) -> pd.DataFrame:
    """Highest-starred repos per type stratum; ties broken by a seeded random key."""
    df = eligible.sort_values("full_name").reset_index(drop=True)
    df["_tie"] = np.random.default_rng(seed).random(len(df))
    alloc = allocate(df["type"].value_counts().to_dict(), n, min_per)
    parts = [df[df["type"] == t].sort_values(["stars", "_tie"], ascending=[False, True]).head(k)
             for t, k in sorted(alloc.items())]
    return pd.concat(parts).drop(columns="_tie").reset_index(drop=True)


def assign_coders(sample: pd.DataFrame, overlap_size: int, seed: int) -> pd.DataFrame:
    """Alternate A/B over type-grouped shuffled order (=> 15/15, balanced by type); round-robin overlap."""
    rng = np.random.default_rng(seed + 1)
    groups = {t: list(rng.permutation(sorted(g["full_name"]))) for t, g in sample.groupby("type")}
    order = [r for t in sorted(groups) for r in groups[t]]
    coder = {r: "AB"[i % 2] for i, r in enumerate(order)}
    overlap: list[str] = []
    pools = {t: list(v) for t, v in groups.items()}
    while len(overlap) < min(overlap_size, len(order)):
        for t in sorted(pools):
            if pools[t] and len(overlap) < overlap_size:
                overlap.append(pools[t].pop(0))
    s = sample.copy()
    s["coder"] = s["full_name"].map(coder)
    s["overlap"] = s["full_name"].isin(overlap)
    return s


# ------------------------------------------------------------------ figure
def flow_figure(flow: pd.DataFrame, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    steps = flow.to_dict("records")
    fig, ax = plt.subplots(figsize=(3.3, 0.55 * len(steps) + 0.3))
    ax.axis("off")
    n = len(steps)
    for i, s in enumerate(steps):
        y = n - i
        ax.text(0.30, y, f"{s['step']}\nn = {s['remaining']}", ha="center", va="center", fontsize=6.5,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="black", lw=0.6))
        if s["excluded"]:
            ax.text(0.80, y + 0.5, f"excluded: {s['excluded']}", ha="center", va="center", fontsize=5.5,
                    bbox=dict(boxstyle="square,pad=0.25", fc="0.9", ec="0.4", lw=0.5))
        if i < n - 1:
            ax.annotate("", xy=(0.30, y - 0.68), xytext=(0.30, y - 0.32), arrowprops=dict(arrowstyle="->", lw=0.6))
    ax.set_xlim(0, 1)
    ax.set_ylim(0.4, n + 0.6)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------ stage
def run(refresh: bool = False, **_) -> pd.DataFrame:
    c = cfg()["select"]
    gh = GitHub(refresh)
    df = pd.read_csv(need(out("s1_candidates.csv"), "search")).fillna({"description": "", "topics": "", "license": ""})
    qlog = pd.read_csv(out("s1_query_log.csv"))
    overrides: dict = c.get("manual_overrides") or {}

    flow = [{"step": "Records identified (all queries)", "remaining": int(qlog["fetched"].sum()), "excluded": 0}]
    excluded: list[dict] = []
    df["needs_manual_check"] = ""

    def drop(mask: pd.Series, step: str, reasons) -> None:
        nonlocal df
        forced = df["full_name"].map(lambda r: overrides.get(r, {}).get("include") is True)
        mask = mask & ~forced
        rs = reasons if isinstance(reasons, pd.Series) else pd.Series(reasons, index=df.index)
        for i in df.index[mask]:
            excluded.append({"full_name": df.at[i, "full_name"], "stars": df.at[i, "stars"], "step": step,
                             "reason": rs[i]})
        df = df[~mask].copy()
        flow.append({"step": step, "remaining": len(df), "excluded": int(mask.sum())})

    flow.append({"step": "Unique repositories", "remaining": len(df),
                 "excluded": flow[0]["remaining"] - len(df)})
    manual_out = df["full_name"].map(lambda r: overrides.get(r, {}).get("include") is False)
    drop(manual_out, "Manual exclusion (config)", df["full_name"].map(lambda r: overrides.get(r, {}).get("reason", "manual")))
    drop(df["fork"].astype(bool), "Forks removed", "fork")
    drop(df["stars"] < cfg()["search"]["min_stars"], f"< {cfg()['search']['min_stars']} stars", "too few stars")
    drop(df["pushed_at"] < c["min_pushed"], f"Last push before {c['min_pushed'][:4]}", "inactive")

    rules = df.apply(lambda r: apply_rules(meta_text(r)), axis=1)
    df["needs_manual_check"] = rules.map(lambda x: ";".join(x[1]))
    drop(rules.map(lambda x: x[0] is not None), "Not a generation tool (metadata)",
         rules.map(lambda x: f"not_generation:{x[0]}"))

    readmes: dict[str, str | None] = {}
    for r in track(df["full_name"], description="S2 READMEs"):
        readmes[r] = gh.readme(r)
    drop(df["full_name"].map(lambda r: not readmes[r]), "No README", "no README")

    probs = df["full_name"].map(lambda r: english_prob(readmes[r]))
    mixed = probs.map(lambda p: p is not None and 0.15 <= p < 0.5)
    df.loc[mixed, "needs_manual_check"] += ";mixed_language_readme"
    df.loc[probs.isna(), "needs_manual_check"] += ";readme_too_short_for_langdetect"
    drop(probs.map(lambda p: p is not None and p < 0.15), "Non-English README",
         probs.map(lambda p: f"non-English README (p_en={p:.2f})" if p is not None else ""))

    head = c["readme_scan_chars"]
    df["type"] = df.apply(lambda r: overrides.get(r["full_name"], {}).get("type")
                          or classify_type(meta_text(r)) or classify_type((readmes[r["full_name"]] or "")[:head]), axis=1)
    drop(df["type"].isna(), "Not a generation tool (no tool-type match)", "no tool-type keyword in metadata/README")
    df["needs_manual_check"] = df["needs_manual_check"].str.strip(";")
    df.to_csv(out("s2_eligible.csv"), index=False)

    sample = stratified_select(df, c["sample_size"], c["min_per_type"], c["seed"])
    sample = assign_coders(sample, c["overlap_size"], c["seed"])
    flow.append({"step": "Selected (stratified by type)", "remaining": len(sample), "excluded": len(df) - len(sample)})

    flow_df = pd.DataFrame(flow)
    flow_df.to_csv(out("s2_flow.csv"), index=False)
    pd.DataFrame(excluded).to_csv(out("s2_excluded.csv"), index=False)
    cols = ["full_name", "url", "type", "stars", "forks", "created_at", "pushed_at", "archived", "license", "language",
            "coder", "overlap", "needs_manual_check", "description"]
    sample = sample[cols].sort_values(["type", "stars"], ascending=[True, False])
    sample.to_csv(out("s2_sample.csv"), index=False)
    flow_figure(flow_df, out("figures", "sample_flow.pdf"))

    t = Table("repo", "type", "stars", "coder", "overlap", "archived", "check", title="S2 sample")
    for _, r in sample.iterrows():
        t.add_row(r.full_name, r.type, str(r.stars), r.coder, "x" if r.overlap else "", "x" if r.archived else "",
                  r.needs_manual_check)
    console.print(t)
    console.print(flow_df.to_string(index=False))
    console.print(f"[green]S2: eligible={len(df)} per type={df['type'].value_counts().to_dict()}; "
                  f"sample per type={sample['type'].value_counts().to_dict()}")
    console.print("[bold yellow]PAUSE POINT:[/] review `needs_manual_check` rows; add `select.manual_overrides` in "
                  "mining/config.yaml and re-run `python -m mining select` before `collect`.")
    return sample
