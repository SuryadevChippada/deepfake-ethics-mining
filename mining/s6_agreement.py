"""S6 - inter-coder agreement (Cohen's kappa) on overlap repos, disagreements list, merged final codes."""
from __future__ import annotations

import pandas as pd
from sklearn.metrics import cohen_kappa_score

from . import console, need, out, write_json
from .codebook import repo_level_columns


def kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa; None when undefined (fewer than 2 pairs or both coders constant on the same label)."""
    if len(a) < 2:
        return None
    if len(set(a) | set(b)) == 1:
        return None
    return float(cohen_kappa_score(a, b))


def percent_agreement(a: list[str], b: list[str]) -> float | None:
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else None


def _norm(v) -> str:
    return "" if pd.isna(v) else str(v).strip().lower()


def load_repo_level(coder: str) -> pd.DataFrame | None:
    p = out("coding", f"coder_{coder}.xlsx")
    if not p.exists():
        return None
    df = pd.read_excel(p, sheet_name="repo_level", dtype=str)
    cols = [c for c in repo_level_columns() if c in df]
    df[cols] = df[cols].map(_norm)
    return df if (df[cols] != "").any().any() else None


def candidate_validity() -> pd.DataFrame:
    """False-positive rate per code hint from the `valid (y/n)` column of both sheets."""
    rows = []
    for coder in "AB":
        p = out("coding", f"coder_{coder}.xlsx")
        if p.exists():
            df = pd.read_excel(p, sheet_name="candidates", dtype=str)
            df["coder"] = coder
            rows.append(df)
    if not rows:
        return pd.DataFrame()
    df = pd.concat(rows)
    df["valid"] = df["valid (y/n)"].map(_norm)
    df = df[df["valid"].isin(["y", "n"])]
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("code")["valid"].agg(coded="count", false_pos=lambda s: (s == "n").sum()).reset_index()
    g["fp_rate"] = (g["false_pos"] / g["coded"]).round(3)
    return g


def run(**_) -> dict:
    cols = repo_level_columns()
    sample = pd.read_csv(need(out("s2_sample.csv"), "select"))
    A, B = load_repo_level("A"), load_repo_level("B")
    status: dict = {"computed": False}
    validity = candidate_validity()
    if not validity.empty:
        validity.to_csv(out("coding", "candidate_validity.csv"), index=False)
    if A is None or B is None:
        missing = [c for c, d in (("A", A), ("B", B)) if d is None]
        status["reason"] = f"repo_level sheet empty or missing for coder(s) {', '.join(missing)}"
        write_json(out("coding", "agreement.json"), status)
        console.print(f"[yellow]S6: {status['reason']}.\n  Next: fill output/coding/coder_A.xlsx and coder_B.xlsx "
                      f"(sheet `repo_level`, incl. all overlap repos), then run `python -m mining agreement`.")
        return status

    overlap = sorted(sample.loc[sample["overlap"], "full_name"])
    a, b = A.set_index("repo"), B.set_index("repo")
    per_code, pairs_a, pairs_b, dis = [], [], [], []
    for col in cols:
        va, vb = [], []
        for r in overlap:
            x, y = a.at[r, col] if r in a.index else "", b.at[r, col] if r in b.index else ""
            if x and y:
                va.append(x)
                vb.append(y)
                if x != y:
                    dis.append({"repo": r, "column": col, "coder_A": x, "coder_B": y, "resolved": ""})
        per_code.append({"column": col, "n": len(va), "kappa": kappa(va, vb), "percent_agreement": percent_agreement(va, vb)})
        pairs_a += [f"{col}={v}" for v in va]
        pairs_b += [f"{col}={v}" for v in vb]
    kdf = pd.DataFrame(per_code)
    kdf.to_csv(out("coding", "kappa.csv"), index=False)

    # Keep previously typed resolutions.
    dpath = out("coding", "disagreements.csv")
    dis_df = pd.DataFrame(dis, columns=["repo", "column", "coder_A", "coder_B", "resolved"])
    if dpath.exists():
        old = pd.read_csv(dpath, dtype=str).fillna("")
        prev = {(r.repo, r.column): r.resolved for r in old.itertuples() if r.resolved}
        dis_df["resolved"] = [prev.get((r.repo, r.column), "") for r in dis_df.itertuples()]
    dis_df.to_csv(dpath, index=False)

    # Merge: primary coder for non-overlap repos; overlap -> agreement, else `resolved`, else A (warned).
    resolved = {(r.repo, r.column): r.resolved for r in dis_df.itertuples() if r.resolved}
    final, unresolved = [], 0
    for s in sample.itertuples():
        src = a if (s.coder == "A" or s.overlap) else b
        row = {"repo": s.full_name}
        for col in cols:
            v = src.at[s.full_name, col] if s.full_name in src.index else ""
            if s.overlap:
                if (s.full_name, col) in resolved:
                    v = resolved[(s.full_name, col)]
                elif any(d["repo"] == s.full_name and d["column"] == col for d in dis):
                    unresolved += 1
            row[col] = v
        final.append(row)
    fdf = pd.DataFrame(final)
    fdf.to_csv(out("coding", "final_codes.csv"), index=False)
    blanks = int((fdf[cols] == "").sum().sum())
    overall = kappa(pairs_a, pairs_b)
    status = {"computed": True, "overlap_repos": len(overlap), "overall_kappa": overall,
              "overall_percent_agreement": percent_agreement(pairs_a, pairs_b), "disagreements": len(dis),
              "unresolved_fallback_to_A": unresolved, "blank_cells_in_final": blanks,
              "complete": blanks == 0 and unresolved == 0}
    write_json(out("coding", "agreement.json"), status)
    console.print(kdf.to_string(index=False))
    console.print(f"[green]S6: overall kappa={overall if overall is None else round(overall, 3)}, "
                  f"{len(dis)} disagreements -> output/coding/disagreements.csv; final_codes.csv written")
    if unresolved:
        console.print(f"[yellow]{unresolved} disagreements unresolved -> fell back to coder A. Fill `resolved` in "
                      "disagreements.csv and re-run `agreement`.")
    if blanks:
        console.print(f"[yellow]{blanks} blank cells in final_codes.csv - results stay PRELIMINARY until complete.")
    return status
