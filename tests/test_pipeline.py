"""Unit tests: keyword matching, default parsing, pseudonymisation, kappa, stratified selection."""
import pandas as pd
import pytest

from mining import pseudonymise, scrub
from mining.codebook import CODES_BY_ID, find_keywords, framing_hint, issue_category_hint
from mining.s2_select import allocate, assign_coders, stratified_select
from mining.s4_extract import aggregate_status, parse_default, statement_at
from mining.s6_agreement import kappa, percent_agreement


# ---------------------------------------------------------------- keyword matching
def test_keywords_word_boundaries():
    pats = CODES_BY_ID["GENDER_FEATURE"].patterns
    assert find_keywords("female voice", pats) == ["female"]          # 'male' must not match inside 'female'
    assert find_keywords("is_male = True", pats) == ["male"]          # underscore is a separator
    assert find_keywords("formale analysis", pats) == []


def test_keywords_nsfw_identifiers():
    pats = CODES_BY_ID["NSFW_FILTER"].patterns
    assert find_keywords("if predict_nsfw(frame):", pats) == ["nsfw"]
    assert find_keywords("parser.add_argument('--skip-nsfw')", pats) == ["nsfw"]
    assert find_keywords("unsafe = False", pats) == []


def test_framing_and_issue_hints():
    assert framing_hint("The authors are not responsible for any misuse.") == "liability_shift"
    assert framing_hint("Do not use this tool to create pornography.") == "prohibition"
    assert framing_hint("We are committed to responsible AI.") == "commitment"
    assert framing_hint("Supports 30 languages.") == "descriptive"
    assert issue_category_hint("Please add an NSFW mode for female faces") == "sexual_use"
    assert issue_category_hint("Female voices sound robotic") == "quality_complaint"


# ---------------------------------------------------------------- default parsing
@pytest.mark.parametrize("stmt,expected", [
    ("parser.add_argument('--nsfw-filter', action='store_true')", ("off", "argparse")),
    ("parser.add_argument('--skip-nsfw', action='store_true', help='skip nsfw check')", ("optional", "argparse")),
    ("parser.add_argument('--nsfw-filter', action='store_false')", ("optional", "argparse")),
    ("parser.add_argument('--no-watermark', action='store_false')", ("off", "argparse")),
    ("parser.add_argument('--watermark', default=True, type=bool)", ("optional", "argparse")),
    ("parser.add_argument('--watermark', default=False)", ("off", "argparse")),
    ("parser.add_argument('-n', '--disable-nsfw', default=False)", ("optional", "argparse")),
    ("def swap(frame, nsfw_check=True):", ("on", "function_default")),
    ("def swap(frame, skip_nsfw: bool = True):", ("off", "function_default")),
    ("nsfw_filter: false", ("off", "config")),
    ('"enable_watermark": true,', ("optional", "config")),
    ("x = os.environ.get('DISABLE_NSFW', '0')", ("optional", "env_var")),
    ("gr.Checkbox(label='NSFW filter', value=True)", ("optional", "ui_checkbox")),
    ("if predict_nsfw(frame): return", None),
])
def test_parse_default(stmt, expected):
    assert parse_default(stmt) == expected


def test_statement_spans_multiline_argparse():
    lines = ["parser.add_argument(", "    '--nsfw',", "    action='store_true',", "    help='enable nsfw filter')", "x=1"]
    stmt = statement_at(lines, 3)
    assert "store_true" in stmt and "x=1" not in stmt
    assert parse_default(stmt) == ("off", "argparse")


def test_aggregate_status():
    assert aggregate_status([None, None]) == "unclear"
    assert aggregate_status(["on", None]) == "on"
    assert aggregate_status(["off"]) == "off"
    assert aggregate_status(["on", "off"]) == "optional"
    assert aggregate_status(["optional"]) == "optional"


# ---------------------------------------------------------------- privacy
def test_pseudonymise_stable_and_opaque(monkeypatch):
    monkeypatch.setenv("PSEUDONYM_SALT", "s")
    a = pseudonymise("Alice")
    assert a == pseudonymise("alice") and a.startswith("user_") and len(a) == 13 and "alice" not in a
    assert a != pseudonymise("bob")
    monkeypatch.setenv("PSEUDONYM_SALT", "other")
    assert pseudonymise("alice") != a
    assert pseudonymise(None) == "user_unknown"


def test_scrub_removes_handles_and_emails():
    t = scrub("thanks @octocat, mail me at jane.doe@example.org")
    assert "octocat" not in t and "jane.doe" not in t and "@user" in t and "<email>" in t


# ---------------------------------------------------------------- kappa
def test_kappa_values():
    assert kappa(["yes", "no", "yes", "no"], ["yes", "no", "yes", "no"]) == pytest.approx(1.0)
    assert kappa(["yes", "yes", "no", "no"], ["yes", "no", "yes", "no"]) == pytest.approx(0.0)
    # Textbook example: po=0.7, pe=0.5 -> kappa=0.4
    a = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
    b = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
    assert kappa(a, b) == pytest.approx(0.4)
    assert kappa(["yes"] * 3, ["yes"] * 3) is None      # undefined, both constant
    assert kappa(["yes"], ["no"]) is None
    assert percent_agreement(["a", "b"], ["a", "c"]) == 0.5


# ---------------------------------------------------------------- selection
def _pool():
    rows = []
    for t, n in [("face_swap", 40), ("voice", 100), ("talking_head_lipsync", 50), ("full_body_or_other", 6)]:
        rows += [{"full_name": f"{t}/r{i}", "type": t, "stars": 1000 - (i // 2)} for i in range(n)]  # ties in pairs
    return pd.DataFrame(rows)


def test_allocate_proportional_with_minimum():
    a = allocate({"face_swap": 40, "voice": 100, "talking_head_lipsync": 50, "full_body_or_other": 6}, 30, 4)
    assert sum(a.values()) == 30 and min(a.values()) >= 4 and a["voice"] > a["talking_head_lipsync"] > a["face_swap"]
    assert allocate({"a": 2, "b": 100}, 30, 4)["a"] == 2   # capped by stratum size


def test_stratified_selection_deterministic():
    s1 = stratified_select(_pool(), 30, 4, seed=7)
    s2 = stratified_select(_pool().sample(frac=1, random_state=1), 30, 4, seed=7)
    assert list(s1["full_name"]) == list(s2["full_name"])            # independent of input order
    assert len(s1) == 30 and s1["type"].value_counts().min() >= 4
    c = assign_coders(s1, 8, seed=7)
    assert (c["coder"] == "A").sum() == 15 and c["overlap"].sum() == 8
    assert c["overlap"].groupby(c["type"]).sum().min() >= 1          # overlap spans all types
    assert c.equals(assign_coders(s1, 8, seed=7))
