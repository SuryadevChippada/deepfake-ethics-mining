"""S8 - output/REPORT.md: everything needed before writing the first draft."""
from __future__ import annotations

import shutil

import pandas as pd

from . import PRELIM, cfg, config_hash, console, need, out, read_json
from .codebook import SAFEGUARDS, STATED
from .s2_select import TYPES


def md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if len(df) else "_none_"


def top_quotes(c: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Strongest candidates: most distinct keywords, framed sentences first, one per repo."""
    if c.empty:
        return c
    c = c.copy()
    c["score"] = c["match"].fillna("").str.count(";") + 1
    c["score"] += c["framing_hint"].fillna("").isin(["liability_shift", "prohibition", "commitment"]) * 2
    c["score"] += c["category_hint"].fillna("").isin(["sexual_use", "ethical_concern"]) * 2
    c["score"] += c["default_hint"].fillna("").str.match(r"^(on|off|optional) ") * 2
    c = c.sort_values("score", ascending=False).drop_duplicates("repo").head(n)
    c["quote"] = c["sentence"].fillna("").str.replace(r"\s+", " ", regex=True).str.slice(0, 220)
    c["source"] = "[" + c["repo"] + "](" + c["link"] + ")"
    hint = c[["framing_hint", "default_hint", "category_hint"]].fillna("").agg(" ".join, axis=1).str.strip()
    return pd.DataFrame({"code": c["code"], "quote": c["quote"], "hint": hint, "source": c["source"]})


def run(**_) -> None:
    nums = read_json(need(out("numbers.json"), "analyze"))
    snap = read_json(out("snapshot.json"), {})
    prelim = bool(nums["prelim"])
    N = nums["repos"]
    sample = pd.read_csv(out("s2_sample.csv"))
    flow = pd.read_csv(out("s2_flow.csv"))
    excl = pd.read_csv(out("s2_excluded.csv"))
    log = pd.read_csv(out("s3_collection_log.csv"))
    cands = pd.read_csv(out("s4_candidates.csv"), low_memory=False)
    contra = pd.read_csv(out("s4_contradictions.csv"))
    sg = pd.read_csv(out("s4_safeguards.csv"))
    agr = read_json(out("coding", "agreement.json"), {}) or {}
    tables = {p.stem: pd.read_csv(p) for p in sorted(out("tables").glob("*.csv"))}
    P = f"**{PRELIM}**" if prelim else ""

    L: list[str] = ["# Deepfake ethics & gender MSR study — pipeline report", ""]
    if prelim:
        L += ["> [!WARNING]", f"> **{PRELIM}.** Every number below comes from keyword matching, not from validated "
              "manual coding. Do not cite as findings. Fill the coding sheets, run `agreement`, then re-run "
              "`analyze` and `report`.", ""]

    # 1 provenance
    L += ["## 1. Snapshot and data volume", "",
          f"- Snapshot (UTC): **{snap.get('snapshot_utc', '?')}**; config hash `{config_hash()}`",
          f"- Search queries (each with `stars:>={cfg()['search']['min_stars']}`, sorted by stars):",
          *[f"  - `{q}`" for q in cfg()["search"]["queries"]],
          f"- Repos collected: {int((log['status'] == 'ok').sum())}/{len(log)}; text files checked out: "
          f"{int(log.get('files', pd.Series(dtype=float)).fillna(0).sum())}; issues: {int(log.get('issues', pd.Series(dtype=float)).fillna(0).sum())}, "
          f"PRs: {int(log.get('prs', pd.Series(dtype=float)).fillna(0).sum())}, comments (keyword-matched threads): "
          f"{int(log.get('comments', pd.Series(dtype=float)).fillna(0).sum())}; HF model cards: "
          f"{int(log.get('hf_cards', pd.Series(dtype=float)).fillna(0).sum())}",
          f"- Issue cap per repo: {cfg()['collect']['issue_cap']} (truncated repos: "
          f"{', '.join(log.loc[log.get('issues_truncated', False) == True, 'full_name']) or 'none'})",  # noqa: E712
          f"- Candidates extracted: {len(cands)} (RQ1 {int((cands['rq'] == 'RQ1').sum())}, RQ2 code "
          f"{int((cands['rq'] == 'RQ2').sum())}, RQ2 doc claims {int((cands['rq'] == 'RQ2_claim').sum())}, RQ3 "
          f"{int((cands['rq'] == 'RQ3').sum())})", ""]
    if (log["status"] != "ok").any():
        L += ["Collection errors:", "", md(log.loc[log["status"] != "ok", ["full_name", "error"]]), ""]

    # 2 sampling
    L += ["## 2. Sampling flow (→ Method)", "", md(flow), "", "Figure: `output/figures/sample_flow.pdf`", "",
          "Exclusion reasons:", "", md(excl.groupby(["step", "reason"]).size().reset_index(name="n")
                                       .sort_values("n", ascending=False).head(25)), ""]
    ch = sample[sample["needs_manual_check"].notna() & (sample["needs_manual_check"] != "")]
    if len(ch):
        L += ["**Sampled repos needing a manual eligibility check** (exclude via `select.manual_overrides`):", "",
              md(ch[["full_name", "type", "stars", "needs_manual_check", "description"]]), ""]

    # 3 sample
    L += ["## 3. Sample", "", f"{N} repos — " + ", ".join(f"{t}: {nums[f'type_{t}']}" for t in TYPES) +
          f"; archived: {nums['archived']}; overlap (both coders): {nums['overlap']}; median stars {nums['stars_median']}.",
          "", md(tables.get("t1_sample", pd.DataFrame())), ""]

    # 4 RQs
    stated = ", ".join(f"{c.id} {nums[f'stated_{c.id}']}/{N}" for c in STATED)
    L += ["## 4. Results per RQ", "", f"### RQ1 — stated values {P}", "", f"Key counts: {stated}. Any ethics statement: "
          f"{nums['stated_any_ethics']}/{N}; no stated value at all: {nums['stated_none']}/{N}.", "",
          md(tables.get("t2_rq1_stated", pd.DataFrame())), "", "Framing (automatic hint):", "",
          md(tables.get("t2b_rq1_framing", pd.DataFrame())), "",
          f"Timeline: {nums.get('timeline_repos', 0)} repos with a dated first ethics statement; median lag after repo "
          f"creation {nums.get('timeline_median_lag_days', 'n/a')} days; " + ", ".join(
              f"after {e['label']}: {nums.get('first_after_' + e['id'], 0)}" for e in cfg()["extract"]["events"]) + ".",
          "", "Figures: `output/figures/f1_rq1_timeline.pdf`", "", "Strongest example quotes:", "",
          md(top_quotes(cands[(cands["rq"] == "RQ1") & (cands["code"] != "BENEFICENCE")])), "",
          f"**Plain-language summary.** {nums['stated_any_ethics']} of {N} repositories contain at least one "
          f"ethics-related statement in their documentation, most often non-maleficence ({nums['stated_NON_MALEFICENCE']}) "
          f"and liability/responsibility language ({nums['stated_LIABILITY_SHIFT']}). Consent is mentioned in "
          f"{nums['stated_CONSENT']} and transparency/labelling in {nums['stated_TRANSPARENCY']} repositories. "
          f"The framing hint suggests how often statements shift liability to users rather than commit the project; "
          f"this must be confirmed by coding.", ""]

    enacted = ", ".join(f"{s.id} {nums[f'enacted_{s.id}']}/{N}" for s in SAFEGUARDS)
    L += [f"### RQ2 — enacted safeguards {P}", "", f"Key counts: {enacted}; any safeguard: {nums['enacted_any']}/{N}. "
          f"NSFW filter default: on {nums['default_NSFW_FILTER_on']}, optional {nums['default_NSFW_FILTER_optional']}, "
          f"off {nums['default_NSFW_FILTER_off']}, unclear {nums['default_NSFW_FILTER_unclear']}.", "",
          md(tables.get("t3_rq2_safeguards", pd.DataFrame())), "", "Stated vs. enacted:", "",
          md(tables.get("t3b_rq2_stated_vs_enacted", pd.DataFrame())), "",
          "Figure: `output/figures/f2_rq2_defaults_by_type.pdf`", "", "Strongest example evidence:", "",
          md(top_quotes(cands[cands["rq"] == "RQ2"])), "",
          f"**Plain-language summary.** {nums['enacted_any']} of {N} repositories contain code matching at least one "
          f"safeguard keyword; NSFW filters appear in {nums['enacted_NSFW_FILTER']} and watermarking in "
          f"{nums['enacted_WATERMARK']}. Where a default could be parsed, many safeguards can be switched off by a flag "
          f"(`optional`) — whether a safeguard is really on by default needs manual confirmation. "
          f"{nums['contradictions']} stated-vs-enacted mismatches were flagged automatically (Section 5).", ""]

    top_cat = max(["feature_request", "quality_complaint", "data_practice", "sexual_use", "ethical_concern", "other"],
                  key=lambda k: nums["issues_" + k])
    L += [f"### RQ3 — gender {P}", "", f"Gendered/sexual harm acknowledged: {nums['gendered_harm_ack']}/{N}; data "
          f"demographics documented: {nums['data_demographics_documented']}/{N}; gender as a feature: "
          f"{nums['gender_as_feature']}/{N}. Gender/sexual-term issues/PRs/comments: {nums['issues_gender_total']} in "
          f"{nums['issues_gender_repos']} repos (sexual_use {nums['issues_sexual_use']}, ethical_concern "
          f"{nums['issues_ethical_concern']}, data_practice {nums['issues_data_practice']}).", "",
          md(tables.get("t4_rq3_gender", pd.DataFrame())), "", "Figure: `output/figures/f3_rq3_issue_categories.pdf`", "",
          "Strongest example quotes (docs + pseudonymised issues, ≤25 words):", "",
          md(top_quotes(cands[cands["rq"] == "RQ3"])), "",
          f"**Plain-language summary.** Only {nums['gendered_harm_ack']} of {N} repositories explicitly name sexual or "
          f"gendered harms (e.g. non-consensual intimate imagery) in their documentation. Demographic composition of "
          f"training data is documented in {nums['data_demographics_documented']} repositories, while gender appears "
          f"as a technical feature in {nums['gender_as_feature']}. In issue trackers, the most frequent category hint "
          f"for gender/sexual-term threads is `{top_cat}` ({nums['issues_' + top_cat]} of {nums['issues_gender_total']}); "
          f"sexual-use threads: {nums['issues_sexual_use']}, ethical-concern threads: {nums['issues_ethical_concern']}.", ""]

    L += ["### Breakdown by type and archived status", "", md(tables.get("t5_breakdown", pd.DataFrame())), ""]

    # 5 contradictions, 6 history
    L += [f"## 5. Stated-vs-enacted contradictions {P}", "", md(contra), "",
          f"## 6. Safeguard history (git, author dates) {P}", "",
          md(sg[sg["added_date"].notna()][["repo", "safeguard", "enacted", "default_status", "added_date", "removed_date",
                                           "default_change_dates"]]), "",
          "`removed_date` = last commit touching the keyword when no current code hit exists; "
          "`default_change_dates` = last commits changing a line with the keyword and a default/flag.", ""]

    # 7 kappa
    L += ["## 7. Inter-coder agreement", ""]
    if agr.get("computed"):
        L += [f"Overall Cohen's κ = {agr['overall_kappa']}, percent agreement = {agr['overall_percent_agreement']} on "
              f"{agr['overlap_repos']} overlap repos; disagreements: {agr['disagreements']} "
              f"(unresolved: {agr['unresolved_fallback_to_A']}).", "", md(pd.read_csv(out('coding', 'kappa.csv'))), ""]
    else:
        L += ["Not yet computed – fill coding sheets (`output/coding/coder_A.xlsx`, `coder_B.xlsx`), then run "
              "`python -m mining agreement`.", ""]

    # 8 threats
    vpath = out("coding", "candidate_validity.csv")
    fp = (md(pd.read_csv(vpath)) if vpath.exists() else
          "False-positive rate per code: not yet available (requires `valid (y/n)` in the candidate sheets).")
    eng = excl["reason"].astype(str).str.startswith("non-English").sum()
    L += ["## 8. Threats to validity (data-driven notes)", "",
          "- **Keyword recall:** candidates come from fixed dictionaries (codebook.py); statements phrased differently "
          "are missed. Recall is unmeasured — consider a manual read of 3–5 READMEs end-to-end.",
          f"- **Precision:** {fp}" if not vpath.exists() else "- **Precision (false-positive rate per code):**",
          *([fp] if vpath.exists() else []),
          f"- **Star bias:** sample is top-starred per stratum (median {nums['stars_median']} stars); less popular "
          "tools (incl. many NCII-oriented ones) are under-represented.",
          f"- **Single snapshot:** all data as of {snap.get('snapshot_utc', '?')}; README/issue state may change. "
          "Git author dates can be rewritten (rebases, squashes).",
          f"- **Archived repos:** {nums['archived']} of {N} are archived; their state reflects past norms.",
          f"- **English only:** {eng} repositories excluded for non-English READMEs (often Chinese-language tools).",
          "- **Search frame:** GitHub search covers name/description/topics only; repos removed by GitHub (policy/DMCA) "
          "are invisible. Three queries for full-body tools were added to the brief's list so that the stratum is non-empty.",
          f"- **Issue cap:** at most {cfg()['collect']['issue_cap']} issues/PRs per repo; comments fetched only for "
          f"keyword-matching threads (≤{cfg()['collect']['comment_issue_cap']} per repo).",
          "- **Default parsing:** static heuristics (argparse/config/env/UI); `unclear` defaults need manual reading.", ""]

    # 9 checklist
    L += ["## 9. Paper draft checklist", "", "| Paper section | Feed from |", "|---|---|",
          "| Method: sampling | §2, `output/s2_flow.csv`, `figures/sample_flow.pdf`, `s2_excluded.csv` |",
          "| Method: sample | `latex/t1_sample.tex`, §3 |",
          "| Method: coding & reliability | `coding/CODEBOOK.md`, `coding/kappa.csv`, `coding/agreement.json` |",
          "| Results RQ1 | `latex/t2_rq1_stated.tex`, `t2b_rq1_framing.tex`, `figures/f1_rq1_timeline.pdf`, §4 quotes |",
          "| Results RQ2 | `latex/t3_rq2_safeguards.tex`, `t3b_rq2_stated_vs_enacted.tex`, `figures/f2_rq2_defaults_by_type.pdf`, §5, §6 |",
          "| Results RQ3 | `latex/t4_rq3_gender.tex`, `figures/f3_rq3_issue_categories.pdf`, §4 quotes |",
          "| Discussion (vs. Pawelec 2025) | §4 summaries, `t5_breakdown.tex`, `output/evidence/*.md` |",
          "| Threats to validity | §8 |", "| All numbers in text | `\\input{numbers.tex}` → macros in `numbers.json` |",
          ""]
    if prelim:
        L += [f"---\n\n**{PRELIM}.**"]
    out("REPORT.md").write_text("\n".join(L) + "\n")

    # LaTeX bundle: figures copy next to tables
    for f in out("figures").glob("*.pdf"):
        shutil.copy(f, out("latex", "figures", f.name))
    console.print(f"[green]S8: output/REPORT.md written; LaTeX bundle in output/latex/ "
                  f"({len(list(out('latex').glob('*.tex')))} .tex, figures copied)"
                  f"{'  [' + PRELIM + ']' if prelim else ''}")
