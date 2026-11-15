"""S7 - tables (CSV + booktabs LaTeX), figures (PDF, greyscale-safe, 3.3in) and number macros."""
from __future__ import annotations

import re
from datetime import datetime

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import PRELIM, cfg, console, need, out, read_json, write_json  # noqa: E402
from .codebook import ETHICS_STATEMENT_CODES, ISSUE_CATEGORIES, SAFEGUARDS, STATED, repo_level_columns  # noqa: E402
from .s2_select import TYPES  # noqa: E402

W = 3.3
plt.rcParams.update({"font.size": 7, "axes.titlesize": 7, "legend.fontsize": 6, "pdf.fonttype": 42,
                     "axes.spines.top": False, "axes.spines.right": False})
GREYS = ["0.15", "0.45", "0.7", "0.9", "1.0"]
HATCH = ["", "///", "...", "xx", ""]
TYPE_SHORT = {"face_swap": "Face swap", "talking_head_lipsync": "Talking head", "voice": "Voice",
              "full_body_or_other": "Body/other"}
ABBR = {"TRANSPARENCY": "TR", "NON_MALEFICENCE": "NM", "LIABILITY_SHIFT": "LS", "CONSENT": "CO", "PRIVACY": "PR",
        "JUSTICE_FAIRNESS": "JF", "HUMAN_CONTROL": "HC", "BENEFICENCE": "BE", "LEGAL_REFERENCE": "LR",
        "NSFW_FILTER": "NSFW", "WATERMARK": "WM", "CONSENT_CHECK": "CC", "DETECTION": "DET", "USAGE_RESTRICTION": "UR"}
STATUS_ORDER = ["on", "optional", "off", "unclear"]


# ------------------------------------------------------------------ latex helpers
def tex_escape(s) -> str:
    s = "" if pd.isna(s) else str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"), ("_", r"\_"),
                 ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}")]:
        s = s.replace(a, b)
    return s.replace("✓", r"\checkmark{}").replace("–", "--")


def latex_table(df: pd.DataFrame, name: str, caption: str, prelim: bool, star: bool = False) -> None:
    """Write CSV to output/tables and a booktabs table to output/latex."""
    df.to_csv(out("tables", f"{name}.csv"), index=False)
    env = "table*" if star else "table"
    cap = tex_escape(caption) + (r" \textit{(PRELIMINARY -- automatic, unverified.)}" if prelim else "")
    align = "l" + "r" * (len(df.columns) - 1)
    L = [f"\\begin{{{env}}}", r"\centering", r"\footnotesize", f"\\caption{{{cap}}}", f"\\label{{tab:{name}}}",
         f"\\begin{{tabular}}{{{align}}}", r"\toprule", " & ".join(tex_escape(c) for c in df.columns) + r" \\", r"\midrule"]
    for row in df.itertuples(index=False):
        if str(row[0]).startswith("Total"):
            L.append(r"\midrule")
        L.append(" & ".join(tex_escape(v) for v in row) + r" \\")
    L += [r"\bottomrule", r"\end{tabular}", f"\\end{{{env}}}", ""]
    out("latex", f"{name}.tex").write_text("\n".join(L))


_DIGITS = "Zero One Two Three Four Five Six Seven Eight Nine".split()


def macro_name(key: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", key)
    name = "".join(p[:1].upper() + p[1:].lower() for p in parts if p)
    return "n" + re.sub(r"\d", lambda m: _DIGITS[int(m.group())], name)


def savefig(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(out("figures", f"{name}.pdf"))
    plt.close(fig)


# ------------------------------------------------------------------ data loading
def repo_codes() -> tuple[pd.DataFrame, bool]:
    """Repo-level codes: manual final codes if complete, else automatic S4 features (preliminary)."""
    agr = read_json(out("coding", "agreement.json"), {}) or {}
    if agr.get("complete") and out("coding", "final_codes.csv").exists():
        return pd.read_csv(out("coding", "final_codes.csv"), dtype=str).fillna(""), False
    return pd.read_csv(need(out("s4_repo_features.csv"), "extract")), True


def yes(s: pd.Series) -> pd.Series:
    return s.astype(str).str.lower().eq("yes")


# ------------------------------------------------------------------ stage
def run(**_) -> dict:
    sample = pd.read_csv(need(out("s2_sample.csv"), "select"))
    codes, prelim = repo_codes()
    feats = pd.read_csv(out("s4_repo_features.csv"))
    sg = pd.read_csv(out("s4_safeguards.csv"))
    tl = pd.read_csv(out("s4_timeline.csv")) if out("s4_timeline.csv").stat().st_size > 1 else pd.DataFrame()
    cands = pd.read_csv(out("s4_candidates.csv"), low_memory=False)
    contra = pd.read_csv(out("s4_contradictions.csv"))
    df = sample.merge(codes, left_on="full_name", right_on="repo", how="inner")
    N = len(df)
    nums: dict = {"repos": N, "prelim": int(prelim)}
    for t in TYPES:
        nums[f"type_{t}"] = int((df["type"] == t).sum())
    nums["archived"] = int(df["archived"].sum())
    nums["overlap"] = int(df["overlap"].sum())
    nums["stars_median"] = int(df["stars"].median())

    # ---- T1 sample overview
    t1 = df[["full_name", "type", "stars", "created_at", "archived", "license", "coder", "overlap"]].copy()
    t1["type"] = t1["type"].map(TYPE_SHORT)
    t1["created_at"] = t1["created_at"].str[:7]
    t1["archived"] = t1["archived"].map({True: "✓", False: "–"})
    t1["coder"] = t1["coder"] + t1["overlap"].map({True: "+B", False: ""}).where(t1["coder"] == "A", t1["overlap"].map({True: "+A", False: ""}))
    t1 = t1.drop(columns="overlap").rename(columns={"full_name": "Repository", "type": "Type", "stars": "Stars",
                                                   "created_at": "Created", "archived": "Arch.", "license": "License",
                                                   "coder": "Coder"})
    latex_table(t1, "t1_sample", f"Sample of {N} open-source deepfake repositories.", False, star=True)

    # ---- T2 RQ1 stated values
    t2 = pd.DataFrame({"Repository": df["full_name"]})
    for c in STATED:
        t2[ABBR[c.id]] = yes(df[f"stated_{c.id}"]).map({True: "✓", False: "–"})
        nums[f"stated_{c.id}"] = int(yes(df[f"stated_{c.id}"]).sum())
    eth = pd.concat([yes(df[f"stated_{c}"]) for c in ETHICS_STATEMENT_CODES], axis=1).any(axis=1)
    nums["stated_any_ethics"] = int(eth.sum())
    nums["stated_none"] = int((~pd.concat([yes(df[f"stated_{c.id}"]) for c in STATED], axis=1).any(axis=1)).sum())
    t2.loc[len(t2)] = [f"Total (of {N})"] + [str(nums[f"stated_{c.id}"]) for c in STATED]
    latex_table(t2, "t2_rq1_stated", "RQ1: stated values per repository (" + ", ".join(
        f"{ABBR[c.id]}={c.id.replace('_', ' ').title()}" for c in STATED) + ").", prelim, star=True)
    rq1 = cands[cands["rq"] == "RQ1"]
    fr = rq1.groupby("framing_hint").agg(candidates=("candidate_id", "count"), repos=("repo", "nunique")).reset_index()
    fr = fr.rename(columns={"framing_hint": "Framing", "candidates": "Candidates", "repos": "Repos"})
    latex_table(fr, "t2b_rq1_framing", "RQ1: framing of stated-value candidates (automatic hint).", True)
    for r in fr.itertuples():
        nums[f"framing_{r.Framing}_repos"] = int(r.Repos)

    # ---- F1 timeline
    if len(tl):
        tl = tl[tl["code"].isin(ETHICS_STATEMENT_CODES) & tl["first_date"].notna()]
        first = tl.groupby("repo").agg(first=("first_date", "min"), created=("created_at", "first")).reset_index()
        first["first"] = pd.to_datetime(first["first"], utc=True)
        first["created"] = pd.to_datetime(first["created"], utc=True)
        first = first.sort_values("created")
        nums["timeline_repos"] = len(first)
        lag = (first["first"] - first["created"]).dt.days.clip(lower=0)
        nums["timeline_median_lag_days"] = int(lag.median()) if len(lag) else 0
        for ev in cfg()["extract"]["events"]:
            nums[f"first_after_{ev['id']}"] = int((first["first"] > pd.Timestamp(ev["date"], tz="UTC")).sum())
        fig, ax = plt.subplots(figsize=(W, max(2.2, 0.14 * len(first) + 0.8)))
        y = range(len(first))
        ax.hlines(list(y), first["created"], first["first"], color="0.6", lw=0.6)
        ax.plot(first["created"], list(y), "o", mfc="white", mec="black", ms=3, label="Repo created")
        ax.plot(first["first"], list(y), "s", color="black", ms=3, label="First ethics statement")
        for i, ev in enumerate(cfg()["extract"]["events"]):
            ax.axvline(pd.Timestamp(ev["date"], tz="UTC"), color="0.3", ls=["--", ":", "-."][i % 3], lw=0.7)
            ax.text(pd.Timestamp(ev["date"], tz="UTC"), len(first) - 0.3, ev["label"], rotation=90, fontsize=5,
                    va="top", ha="right")
        ax.set_yticks(list(y), [r.split("/")[1][:22] for r in first["repo"]], fontsize=5)
        ax.legend(loc="lower right", frameon=False)
        savefig(fig, "f1_rq1_timeline")
    else:
        nums["timeline_repos"] = 0

    # ---- T3 RQ2 safeguards
    t3 = pd.DataFrame({"Repository": df["full_name"]})
    short = {"on": "on", "optional": "opt", "off": "off", "unclear": "?", "NA": "–", "na": "–", "": "–"}
    for s in SAFEGUARDS:
        en = yes(df[f"enacted_{s.id}"])
        t3[ABBR[s.id]] = df[f"default_{s.id}"].astype(str).where(en, "NA").map(lambda v: short.get(v, v))
        nums[f"enacted_{s.id}"] = int(en.sum())
        for st in STATUS_ORDER:
            nums[f"default_{s.id}_{st}"] = int((en & df[f"default_{s.id}"].astype(str).eq(st)).sum())
    any_sg = pd.concat([yes(df[f"enacted_{s.id}"]) for s in SAFEGUARDS], axis=1).any(axis=1)
    nums["enacted_any"] = int(any_sg.sum())
    t3.loc[len(t3)] = [f"Total enacted (of {N})"] + [str(nums[f"enacted_{s.id}"]) for s in SAFEGUARDS]
    latex_table(t3, "t3_rq2_safeguards", "RQ2: safeguards per repository and default status (on / opt = can be "
                "disabled / off / ? = unclear / – = absent).", prelim, star=True)
    sgs = sg[sg["repo"].isin(df["full_name"])]
    ct = []
    for s in SAFEGUARDS:
        x = sgs[sgs["safeguard"] == s.id]
        st, en = x["claimed_in_docs"].astype(bool), x["enacted"].astype(bool)
        row = {"Safeguard": ABBR[s.id], "Stated & enacted": int((st & en).sum()), "Stated only": int((st & ~en).sum()),
               "Enacted only": int((~st & en).sum()), "Neither": int((~st & ~en).sum())}
        ct.append(row)
        nums[f"stated_only_{s.id}"] = row["Stated only"]
        nums[f"stated_enacted_{s.id}"] = row["Stated & enacted"]
    latex_table(pd.DataFrame(ct), "t3b_rq2_stated_vs_enacted", "RQ2: stated (docs) vs. enacted (code) safeguards.", True)
    nums["contradictions"] = len(contra[contra["repo"].isin(df["full_name"])])
    nums["safeguards_removed"] = int(sgs["removed_date"].notna().sum())

    # ---- F2 default status by type
    rows = []
    for t in TYPES:
        sub = df[df["type"] == t]
        for st in STATUS_ORDER:
            rows.append({"type": t, "status": st, "n": int(sum((yes(sub[f"enacted_{s.id}"]) &
                                                               sub[f"default_{s.id}"].astype(str).eq(st)).sum()
                                                              for s in SAFEGUARDS))})
    f2 = pd.DataFrame(rows).pivot(index="type", columns="status", values="n").reindex(TYPES)[STATUS_ORDER]
    f2.to_csv(out("tables", "f2_data.csv"))
    fig, ax = plt.subplots(figsize=(W, 1.9))
    bottom = pd.Series(0, index=f2.index)
    for i, st in enumerate(STATUS_ORDER):
        ax.bar([TYPE_SHORT[t] for t in f2.index], f2[st], bottom=bottom, color=GREYS[i], hatch=HATCH[i],
               edgecolor="black", lw=0.5, label=st)
        bottom += f2[st]
    ax.set_ylabel("Safeguard instances (repo × safeguard)")
    ax.legend(ncol=4, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.18))
    savefig(fig, "f2_rq2_defaults_by_type")

    # ---- T4 RQ3 gender
    for col in ("gendered_harm_ack", "data_demographics_documented", "gender_as_feature"):
        nums[col] = int(yes(df[col]).sum())
    ig = cands[(cands["code"] == "ISSUE_GENDER") & cands["repo"].isin(df["full_name"])]
    issue_counts = feats.set_index("repo").reindex(df["full_name"])
    t4 = []
    for t in TYPES + ["all"]:
        sub = df if t == "all" else df[df["type"] == t]
        r = {"Type": "Total" if t == "all" else TYPE_SHORT[t], "Repos": len(sub),
             "Harm ack.": int(yes(sub["gendered_harm_ack"]).sum()),
             "Data demogr.": int(yes(sub["data_demographics_documented"]).sum()),
             "Gender feature": int(yes(sub["gender_as_feature"]).sum())}
        for cat in ISSUE_CATEGORIES:
            col = f"issues_{cat}"
            r[cat.replace("_", " ")] = int(issue_counts.loc[sub["full_name"], col].fillna(0).sum()) if col in issue_counts else 0
        t4.append(r)
    t4 = pd.DataFrame(t4)
    latex_table(t4, "t4_rq3_gender", "RQ3: gendered harm acknowledgement, demographic data documentation, gender as "
                "feature, and gender/sexual-term issues by category (automatic category hint).", prelim, star=True)
    for cat in ISSUE_CATEGORIES:
        nums[f"issues_{cat}"] = int(t4.iloc[-1][cat.replace("_", " ")])
    nums["issues_gender_total"] = int(sum(nums[f"issues_{c}"] for c in ISSUE_CATEGORIES))
    nums["issues_gender_repos"] = int(ig["repo"].nunique())
    nums["issues_scanned"] = int(feats["n_issues_scanned"].sum())
    nums["comments_scanned"] = int(feats["n_comments_scanned"].sum())

    # ---- F3 issue categories by type
    f3 = t4.iloc[:-1].set_index("Type")[[c.replace("_", " ") for c in ISSUE_CATEGORIES]]
    fig, ax = plt.subplots(figsize=(W, 2.0))
    bottom = pd.Series(0, index=f3.index)
    greys6 = ["0.1", "0.35", "0.55", "0.75", "0.9", "1.0"]
    hatch6 = ["", "///", "", "...", "xx", ""]
    for i, cat in enumerate(f3.columns):
        ax.bar(f3.index, f3[cat], bottom=bottom, color=greys6[i], hatch=hatch6[i], edgecolor="black", lw=0.5, label=cat)
        bottom += f3[cat]
    ax.set_ylabel("Gender/sexual-term issues, PRs, comments")
    ax.legend(ncol=3, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.25))
    savefig(fig, "f3_rq3_issue_categories")

    # ---- breakdown by type and archived
    bd = []
    for label, mask in [*[(TYPE_SHORT[t], df["type"] == t) for t in TYPES], ("Archived", df["archived"]),
                        ("Active", ~df["archived"]), ("Total", pd.Series(True, index=df.index))]:
        sub = df[mask]
        bd.append({"Group": label, "Repos": len(sub),
                   "Ethics stmt.": int(eth[mask].sum()),
                   "Liability shift": int(yes(sub["stated_LIABILITY_SHIFT"]).sum()),
                   "Consent": int(yes(sub["stated_CONSENT"]).sum()),
                   "Any safeguard": int(any_sg[mask].sum()),
                   "NSFW filter": int(yes(sub["enacted_NSFW_FILTER"]).sum()),
                   "Watermark": int(yes(sub["enacted_WATERMARK"]).sum()),
                   "Harm ack.": int(yes(sub["gendered_harm_ack"]).sum())})
    latex_table(pd.DataFrame(bd), "t5_breakdown", "Key counts by tool type and archived status.", prelim)

    # ---- kappa + numbers
    agr = read_json(out("coding", "agreement.json"), {}) or {}
    if agr.get("overall_kappa") is not None:
        nums["kappa_overall"] = round(agr["overall_kappa"], 2)
    snap = read_json(out("snapshot.json"), {})
    nums["snapshot_date"] = snap.get("snapshot_utc", "")[:10]
    write_json(out("numbers.json"), nums)
    L = [f"% Generated {datetime.now():%Y-%m-%d %H:%M} by `python -m mining analyze`. Do not edit by hand.",
         f"% {PRELIM if prelim else 'Based on manual coding (final_codes.csv).'}",
         r"\providecommand{\checkmark}{\ensuremath{\surd}}"]
    L += [f"\\newcommand{{\\{macro_name(k)}}}{{{tex_escape(v)}}}" for k, v in nums.items()]
    out("latex", "numbers.tex").write_text("\n".join(L) + "\n")
    console.print(f"[green]S7: {len(nums)} numbers, tables -> output/tables + output/latex, figures -> output/figures"
                  f"{'  [' + PRELIM + ']' if prelim else ''}")
    return nums
