"""S5 - Excel coding sheets for coders A and B (+ CODEBOOK.md). Never overwrites filled sheets without --refresh."""
from __future__ import annotations

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from . import console, need, out
from .codebook import (ALL_CODES, DEFAULT_STATUSES, SAFEGUARD_CLAIM_PATTERNS, FRAMINGS, ISSUE_CATEGORIES, column_choices, repo_level_columns)

CAND_COLS = ["candidate_id", "repo", "rq", "code", "source_type", "file", "line", "match", "sentence", "context", "link",
             "framing_hint", "default_hint", "category_hint"]
FILL_COLS = ["valid (y/n)", "code (final)", "framing", "default_status", "issue_category", "note"]
HEAD = Font(bold=True)
TODO = PatternFill("solid", fgColor="FFF2CC")


def _clean(v):
    """Excel-safe cell value: drop NaN, XML-illegal control chars and lone surrogates (from issue text)."""
    if isinstance(v, float) and pd.isna(v):
        return None
    if isinstance(v, str):
        return ILLEGAL_CHARACTERS_RE.sub("", v).encode("utf-8", "replace").decode("utf-8")[:32000]
    return v


def _has_entries(path) -> bool:
    """True if a coder already typed anything into a sheet (protects manual work)."""
    if not path.exists():
        return False
    wb = load_workbook(path, read_only=True)
    for name, first_fill in (("candidates", len(CAND_COLS) + 1), ("repo_level", 4)):
        if name in wb.sheetnames:
            for row in wb[name].iter_rows(min_row=2, min_col=first_fill, values_only=True):
                if any(v not in (None, "") for v in row):
                    return True
    return False


def _list_validation(ws, lists_ws, key: str, values: list[str], col_letter: str, n_rows: int, registry: dict) -> None:
    if key not in registry:
        c = len(registry) + 1
        for i, v in enumerate(values, 1):
            lists_ws.cell(row=i, column=c, value=v)
        letter = lists_ws.cell(row=1, column=c).column_letter
        registry[key] = f"lists!${letter}$1:${letter}${len(values)}"
    dv = DataValidation(type="list", formula1=registry[key], allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{col_letter}2:{col_letter}{max(n_rows + 1, 2)}")


def build_workbook(coder: str, cands: pd.DataFrame, repos: pd.DataFrame) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "candidates"
    lists = wb.create_sheet("lists")
    lists.sheet_state = "hidden"
    reg: dict = {}
    ws.append(CAND_COLS + FILL_COLS)
    for r in cands[CAND_COLS].itertuples(index=False):
        ws.append([_clean(v) for v in r] + [None] * len(FILL_COLS))
    n = len(cands)
    base = len(CAND_COLS)
    choices = [["y", "n"], [c.id for c in ALL_CODES] + ["OTHER"], FRAMINGS, DEFAULT_STATUSES + ["NA"], ISSUE_CATEGORIES]
    for k, vals in enumerate(choices):
        col = ws.cell(row=1, column=base + k + 1).column_letter
        _list_validation(ws, lists, FILL_COLS[k], vals, col, n, reg)
    for k in range(len(FILL_COLS)):
        ws.cell(row=1, column=base + k + 1).fill = TODO
    for cell in ws[1]:
        cell.font = HEAD
    for col, w in zip("ABCDEFGHIJKLMNOPQRST", [9, 28, 9, 18, 10, 30, 6, 18, 60, 60, 40, 14, 18, 16, 8, 18, 14, 14, 14, 30]):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2, min_col=9, max_col=10):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    rl = wb.create_sheet("repo_level")
    cols = repo_level_columns()
    rl.append(["repo", "type", "overlap"] + cols + ["note"])
    for r in repos.itertuples(index=False):
        rl.append([r.full_name, r.type, "yes" if r.overlap else "no"] + [None] * (len(cols) + 1))
    for j, col in enumerate(cols):
        letter = rl.cell(row=1, column=4 + j).column_letter
        _list_validation(rl, lists, "|".join(column_choices(col)), column_choices(col), letter, len(repos), reg)
        rl.cell(row=1, column=4 + j).fill = TODO
    for cell in rl[1]:
        cell.font = HEAD
    rl.column_dimensions["A"].width = 38
    rl.freeze_panes = "D2"

    cb = wb.create_sheet("codebook")
    cb.append(["code", "RQ", "scope", "definition", "include", "exclude", "example", "keywords"])
    for c in ALL_CODES:
        cb.append([c.id, c.rq, c.scope, c.definition, c.include, c.exclude, c.example, ", ".join(c.patterns)])
    for cell in cb[1]:
        cell.font = HEAD
    for col, w in zip("ABCDEFGH", [20, 6, 8, 60, 50, 40, 50, 60]):
        cb.column_dimensions[col].width = w
    wb.move_sheet("lists", offset=1)
    return wb


def codebook_md() -> str:
    L = ["# Codebook", "", "Keyword dictionaries generate *candidates*; coders decide validity, final code and attributes.",
         "", "Framing values: " + ", ".join(FRAMINGS) + ". `descriptive` = states the value without commitment, "
         "prohibition or liability language.", "",
         "Default status: `on` = safeguard active by default with no user switch; `optional` = active by default but "
         "can be disabled via flag/config/UI; `off` = present but disabled unless the user opts in; `unclear`; `NA` = "
         "safeguard not present.", "", "Issue categories: " + ", ".join(ISSUE_CATEGORIES) + ".", ""]
    for rq in ("RQ1", "RQ2", "RQ3"):
        L += [f"## {rq}", ""]
        for c in [c for c in ALL_CODES if c.rq == rq]:
            L += [f"### {c.id} ({c.scope})", "", f"- **Definition:** {c.definition}", f"- **Include:** {c.include}",
                  f"- **Exclude:** {c.exclude}", f"- **Example:** {c.example}",
                  f"- **Keywords (regex):** `{'`, `'.join(c.patterns)}`", ""]
    L += ["## Safeguard claims in docs (rq = RQ2_claim)", "",
          "Docs are matched with stricter patterns than code, so value statements are not counted as claims:", ""]
    L += [f"- `{k}`: `{'`, `'.join(v)}`" for k, v in SAFEGUARD_CLAIM_PATTERNS.items()] + [""]
    L += ["## Repo-level columns", "", "One row per repository in sheet `repo_level`:", ""]
    L += [f"- `{c}`: {' / '.join(column_choices(c))}" for c in repo_level_columns()]
    return "\n".join(L) + "\n"


def run(refresh: bool = False, **_) -> None:
    cands = pd.read_csv(need(out("s4_candidates.csv"), "extract"))
    sample = pd.read_csv(need(out("s2_sample.csv"), "select"))
    out("coding", "CODEBOOK.md").write_text(codebook_md())
    for coder in "AB":
        repos = sample[(sample["coder"] == coder) | sample["overlap"]].sort_values("full_name")
        path = out("coding", f"coder_{coder}.xlsx")
        if _has_entries(path) and not refresh:
            console.print(f"[yellow]{path.name} already contains coding - not overwritten (use --refresh to force).")
            continue
        c = cands[cands["repo"].isin(repos["full_name"])].sort_values(["repo", "rq", "code", "candidate_id"])
        build_workbook(coder, c, repos).save(path)
        console.print(f"[green]S5: {path.name}: {len(repos)} repos ({int(repos['overlap'].sum())} overlap), "
                      f"{len(c)} candidates")
    console.print("[green]S5: output/coding/CODEBOOK.md written")
