# Deepfake ethics & gender — repository-mining pipeline

An MSR study of 30 open-source deepfake repositories, covering stated values (RQ1), enacted safeguards (RQ2) and gender (RQ3).
Everything is configured in `mining/config.yaml`. Keyword dictionaries and code definitions are in `mining/codebook.py`.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN=...        # or be logged in with `gh auth login`
# optional: export PSEUDONYM_SALT=<secret>   (keep it private, don't commit it)
```

## Run

```bash
python -m mining run-all                     # all stages; cached, so re-runs are cheap
python -m mining <stage> [--refresh] [--repo owner/name]
pytest
```

| Stage | Reads | Writes |
|---|---|---|
| `search` | config | `output/s1_candidates.csv`, `s1_query_log.csv`, `snapshot.json` |
| `select` | S1 | `output/s2_flow.csv`, `s2_excluded.csv`, `s2_eligible.csv`, `s2_sample.csv`, `figures/sample_flow.pdf` |
| `collect` | S2 | `data/repos/*` (blobless text-only clones), `data/raw/<repo>/*`, `output/s3_collection_log.csv` |
| `extract` | S3 | `output/s4_candidates.csv`, `s4_repo_features.csv`, `s4_timeline.csv`, `s4_safeguards.csv`, `s4_contradictions.csv`, `evidence/*.md` |
| `sheets` | S4 | `output/coding/coder_A.xlsx`, `coder_B.xlsx`, `CODEBOOK.md` (filled sheets are never overwritten without `--refresh`) |
| `agreement` | sheets | `output/coding/kappa.csv`, `disagreements.csv`, `final_codes.csv`, `agreement.json`, `candidate_validity.csv` |
| `analyze` | S4 + coding | `output/tables/*.csv`, `latex/*.tex`, `figures/*.pdf`, `numbers.json`, `latex/numbers.tex` |
| `report` | all | `output/REPORT.md`, `output/latex/figures/` |

## Manual workflow

1. **After `select`:** review the sampled repos that have `needs_manual_check` set (in `s2_sample.csv` and REPORT §2). To drop or retype a repo, add it under `select.manual_overrides` in the config, re-run `select`, then run `collect` onwards.
2. **Code:** each coder fills their workbook. In the `candidates` sheet, set `valid`, `code`, `framing`, `default_status` and `issue_category`. In the `repo_level` sheet, fill one row per repo. Overlap repos appear in both workbooks.
3. Run `python -m mining agreement`, then discuss the rows in `output/coding/disagreements.csv` and fill the `resolved` column. Run `agreement` again.
4. Run `python -m mining analyze report`. The "PRELIMINARY" labels disappear once `final_codes.csv` is complete.
5. In LaTeX, `\input{numbers.tex}` and the table files from `output/latex/`, then use macros such as `\nStatedConsent`.

## Ethics, safety and privacy

- Code from mined repositories is never executed, imported or installed. Clones use `--filter=blob:none --no-checkout`, LFS smudge is off, and hooks are disabled. Only text files of 2 MB or less are checked out. No weights, datasets, media or release assets are downloaded.
- Issue/PR authors are stored only as `user_<sha256(salt+login)[:8]>` plus a role (`maintainer`/`user`). @handles and e-mail addresses are scrubbed from text. Git history is read with `%aI` (author date) only, so no names or e-mails are collected.
- Every API response is cached in `data/cache/`. The token is never written to disk.
