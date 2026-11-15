# deepfake-ethics-mining

We analyse 30 open-source deepfake projects on GitHub to answer three questions:

1. **What do they say?** Which ethics statements appear in READMEs and docs (disclaimers, consent, misuse warnings)?
2. **What do they do?** Are safeguards like NSFW filters or watermarks actually in the code, and are they on by default?
3. **What about gender?** Do projects mention that deepfake harm mostly targets women, or document gender in their data?

Seminar project at TU Darmstadt (WS 2026/27), building on Pawelec (2025), *"Decent deepfakes?"*, AI and Ethics.

## How it works

```
Search GitHub → pick 30 repos → download text + history → find keyword hits → we check them by hand → tables & figures
```

The scripts only find *candidates*. Every result in the paper is checked manually by two coders.

## Setup

You need Python 3.11+, git and the [GitHub CLI](https://cli.github.com/).

```bash
git clone https://github.com/SuryadevChippada/deepfake-ethics-mining.git
cd deepfake-ethics-mining
pip install -r requirements.txt
gh auth login
```

## Run

```bash
python -m mining run-all
```

Results end up in `output/`:

| File | What it is |
|---|---|
| `REPORT.md` | Summary of all results |
| `s2_sample.csv` | The 30 selected repos |
| `evidence/` | Keyword hits per repo, with links |
| `coding/` | Excel sheets for manual coding |
| `latex/` | Tables, figures and numbers for the paper |

## Manual coding

1. Coder A fills `coding/coder_A.xlsx` and Coder B fills `coding/coder_B.xlsx`.
2. Run `python -m mining agreement` to get Cohen's kappa.
3. Run `python -m mining analyze` and `python -m mining report` to get the final results.

## Ethics

- We never run code from the mined repos.
- We never download model weights or media.
- We store no e-mails, and issue authors are anonymised.

## Authors

<Name 1>, <Name 2> · TU Darmstadt
