"""Codebook: codes, definitions and keyword dictionaries (editable).

Keyword patterns are Python regexes matched case-insensitively with word
boundaries added around each alternative. They produce CANDIDATES only;
every candidate must be validated by a human coder.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass(frozen=True)
class Code:
    id: str
    rq: str                 # RQ1 | RQ2 | RQ3
    scope: str              # docs | code | issues
    definition: str
    include: str
    exclude: str
    example: str
    patterns: tuple[str, ...] = field(default_factory=tuple)


# ------------------------------------------------------------------ RQ1 (docs)
STATED = [
    Code("TRANSPARENCY", "RQ1", "docs",
         "The project states that outputs should be disclosed/labelled as synthetic or traceable.",
         "Statements about labelling, watermarking, disclosure, provenance of generated media.",
         "Transparency about the code itself (open source, changelog).",
         '"Please clearly label any content created with this tool as AI-generated."',
         (r"watermark\w*", r"label(l?ed|l?ing)?", r"disclos\w+", r"synthetic", r"ai[- ]generated",
          r"provenance", r"c2pa", r"clearly (state|mark|indicate)")),
    Code("NON_MALEFICENCE", "RQ1", "docs",
         "The project names possible harms/misuse and expresses that they should be avoided.",
         "Mentions of misuse, harm, malicious/illegal use, fraud, misinformation, defamation.",
         "Harm to the software (bugs, crashes).",
         '"This software must not be used for malicious purposes such as fraud or misinformation."',
         (r"misuse\w*", r"harm\w*", r"malicious\w*", r"illegal\w*", r"abus\w+", r"fraud\w*",
          r"misinformation", r"disinformation", r"defamat\w+", r"deceiv\w+", r"decept\w+", r"unethical")),
    Code("LIABILITY_SHIFT", "RQ1", "docs",
         "Responsibility for use is assigned to the user / developers disclaim liability.",
         "'not responsible', 'at your own risk', 'user is responsible', 'use responsibly'.",
         "Standard licence warranty text (LICENSE files are not scanned for this code).",
         '"The developers are not responsible for any misuse; users are solely responsible."',
         (r"not (be )?(held )?(responsible|liable|accountable)", r"no liability", r"liabilit\w+",
          r"at (your|their) own risk", r"users? (is|are|shall be|will be)( solely| fully)? responsible",
          r"use (it )?responsibl[ey]", r"responsibility", r"disclaim\w*", r"take no responsibility")),
    Code("CONSENT", "RQ1", "docs",
         "The project requires or asks for consent of depicted/cloned persons.",
         "consent, permission, authorization of the person whose face/voice is used.",
         "Permission in the technical sense (file permissions, API scopes).",
         '"Only use faces of people who have given explicit consent."',
         (r"consent\w*", r"permission", r"authori[sz]ation", r"authori[sz]ed", r"without (the )?(person|people|individual|their)\S*")),
    Code("PRIVACY", "RQ1", "docs",
         "The project refers to privacy, personal data or rights to one's likeness/identity.",
         "privacy, personal data, GDPR, likeness, identity theft, impersonation.",
         "Privacy of the developer's telemetry unless tied to depicted persons.",
         '"Respect the privacy and likeness rights of others."',
         (r"privacy", r"personal data", r"gdpr", r"likeness", r"identity theft", r"impersonat\w+", r"biometric\w*")),
    Code("JUSTICE_FAIRNESS", "RQ1", "docs",
         "The project addresses bias, fairness or diversity of the model/data.",
         "bias, fair(ness), diverse, underrepresented, demographic balance.",
         "Bias in the ML-parameter sense (bias term).",
         '"The model may perform worse on darker skin tones due to dataset bias."',
         (r"bias(es|ed)?", r"fairness", r"\bfair\b", r"divers(e|ity)", r"under-?represent\w*", r"demographic\w*", r"discriminat\w+")),
    Code("HUMAN_CONTROL", "RQ1", "docs",
         "Human oversight/control over generation is stated as a value.",
         "human review, human in the loop, manual approval, oversight.",
         "UI controls (sliders, buttons).",
         '"Every output should be reviewed by a human before publication."',
         (r"human[- ]in[- ]the[- ]loop", r"human (oversight|review|control)", r"oversight", r"manual (review|approval)")),
    Code("BENEFICENCE", "RQ1", "docs",
         "Beneficial/legitimate purposes are stated (justification of the tool).",
         "education, research purposes, art/creative, entertainment, accessibility, film industry.",
         "Generic marketing without a purpose claim.",
         '"This project is intended for research and educational purposes only."',
         (r"educational", r"education", r"research purposes?", r"academic (research|purposes?)", r"creative",
          r"entertainment", r"accessibility", r"\bart(istic)?\b", r"film industry", r"positive (use|purpose)s?")),
    Code("LEGAL_REFERENCE", "RQ1", "docs",
         "The project references laws, regulation or terms of service.",
         "law(s), regulation, EU AI Act, comply, local laws, terms of service, copyright.",
         "Licence names only (MIT, GPL).",
         '"Users must comply with local laws and regulations."',
         (r"laws?", r"legal(ly)?", r"regulations?", r"ai act", r"compl(y|iance)", r"terms of (service|use)",
          r"copyright", r"jurisdiction")),
]

# ------------------------------------------------------------------ RQ2 (code)
SAFEGUARDS = [
    Code("NSFW_FILTER", "RQ2", "code",
         "A content filter that detects/blocks sexual or explicit content.",
         "nsfw classifiers, safety checkers, nudity detection invoked on inputs/outputs.",
         "Comments mentioning NSFW without code; dataset labels.",
         "`if predict_nsfw(frame): sys.exit()`",
         (r"nsfw\w*", r"safety_checker", r"safety checker", r"content_filter", r"nudity", r"nudenet", r"opennsfw\w*",
          r"explicit content")),
    Code("WATERMARK", "RQ2", "code",
         "Generated media are marked (visible/invisible watermark, metadata/provenance label).",
         "watermark embedding, invisible-watermark, C2PA manifests, metadata labels.",
         "Watermark removal tools (code as harmful-use evidence, not a safeguard).",
         "`apply_watermark(output, 'AI-generated')`",
         (r"watermark\w*", r"invisible_watermark", r"imwatermark", r"c2pa", r"metadata label", r"ai[_ ]generated[_ ]label")),
    Code("CONSENT_CHECK", "RQ2", "code",
         "A technical check that the depicted person consented (verification, liveness).",
         "consent prompts that block use, identity verification, liveness checks.",
         "Licence acceptance dialogs not tied to depicted persons.",
         "`if not args.i_have_consent: raise SystemExit`",
         (r"consent\w*", r"verify[_ ]identity", r"liveness", r"authori[sz]ation")),
    Code("DETECTION", "RQ2", "code",
         "The tool ships deepfake detection/forensics for its own or others' outputs.",
         "deepfake/fake detectors, forensic classifiers.",
         "Face detection (needed for swapping).",
         "`score = deepfake_detector(video)`",
         (r"deepfake[_ ]detect\w*", r"detect[_ ]deepfakes?", r"fake[_ ]detect\w*", r"forensic\w*", r"real[_ ]or[_ ]fake")),
    Code("USAGE_RESTRICTION", "RQ2", "code",
         "Technical restrictions on whom/what can be processed (block lists, celebrity filters, rate limits).",
         "block/allow lists of faces, celebrity filters, rate limiting, restricted modes.",
         "Generic restrictions unrelated to use (e.g. file type restrictions).",
         "`if face_id in CELEBRITY_BLOCKLIST: skip`",
         (r"block_?list", r"black_?list", r"celebrit\w+", r"face_whitelist", r"white_?list", r"rate[_ ]?limit\w*", r"restricted[_ ]mode")),
]

# ------------------------------------------------------------------ RQ3 (gender)
GENDER = [
    Code("GENDERED_HARM", "RQ3", "docs",
         "Docs acknowledge sexual/gendered harms of deepfakes (NCII, pornography, harassment of women).",
         "non-consensual intimate imagery, porn, nude, sexual, harassment, women as targets.",
         "Neutral mentions of 'NSFW filter' without naming the harm (code under NSFW_FILTER instead).",
         '"Do not create non-consensual pornographic content."',
         (r"women", r"woman", r"female", r"girls?", r"non-?consensual", r"ncii", r"nsii", r"pornograph\w*", r"porn\w*",
          r"sexual\w*", r"intimate", r"revenge porn", r"nudes?", r"naked", r"harass\w*")),
    Code("DATA_DEMOGRAPHICS", "RQ3", "docs",
         "Docs document gender/demographic composition of training data or model performance by group.",
         "gender/sex/age/ethnicity/skin tone composition, named face/voice datasets.",
         "Dataset names used only as download instructions (still a candidate; code as weak).",
         '"Trained on FFHQ (70k faces); performance on darker skin tones was not evaluated."',
         (r"gender", r"\bsex\b", r"\bmale\b", r"female", r"demographic\w*", r"ethnicit\w+", r"\brace\b", r"skin tones?",
          r"\bages?\b", r"dataset composition", r"ffhq", r"celeba(-?hq)?", r"voxceleb\d?", r"libritts", r"vctk", r"librispeech",
          r"vggface\d?", r"ms-?celeb")),
    Code("GENDER_FEATURE", "RQ3", "code",
         "Gender is a feature/parameter of the tool (gender filter, voice gender, pitch presets).",
         "gender variables, male/female options, m2f/f2m pitch presets.",
         "Unrelated identifiers.",
         "`parser.add_argument('--gender', choices=['male', 'female'])`",
         (r"gender\w*", r"\bmale\b", r"female", r"m2f", r"f2m", r"male2female", r"female2male", r"pitch[_ ]?preset\w*",
          r"voice[_ ]gender")),
    Code("ISSUE_GENDER", "RQ3", "issues",
         "Issue/PR text that mentions gender or sexual content.",
         "gender terms, sexual/porn terms in titles, bodies or comments.",
         "Bot-generated text.",
         '"Swap fails on female faces with long hair."',
         (r"gender", r"women", r"woman", r"female", r"\bmale\b", r"girls?", r"boys?", r"feminine", r"masculine",
          r"porn\w*", r"nsfw", r"nudes?", r"naked", r"nudity", r"sexual\w*", r"explicit", r"hentai", r"onlyfans",
          r"non-?consensual", r"\bxxx\b")),
]

ALL_CODES: list[Code] = STATED + SAFEGUARDS + GENDER

# Stricter subsets used only for the automatic (preliminary) repo-level codes.
GENDERED_HARM_STRONG = (r"non-?consensual", r"ncii", r"nsii", r"pornograph\w*", r"porn\w*", r"sexual\w*", r"intimate",
                        r"nudes?", r"naked", r"harass\w*")
DATA_DEMOGRAPHICS_STRONG = (r"gender", r"\bsex\b", r"demographic\w*", r"ethnicit\w+", r"\brace\b", r"skin tones?",
                            r"dataset composition")

# Stricter patterns for safeguard *claims* in docs (a consent value statement is not a consent-check claim).
SAFEGUARD_CLAIM_PATTERNS = {
    "NSFW_FILTER": (r"nsfw[ -]?(filter|check|detect\w*|classifier|protection)", r"safety[ _]checker", r"nudity (filter|detect\w*)",
                    r"(filter|block)s? (out )?(nsfw|nudity|explicit)", r"content filter"),
    "WATERMARK": (r"watermark\w*", r"c2pa", r"content credentials"),
    "CONSENT_CHECK": (r"consent (check|verification|prompt|form)", r"verif(y|ies|ication of) (identity|consent)", r"liveness"),
    "DETECTION": (r"deepfake detect\w*", r"detect(s|ing)? (deepfakes|fakes|manipulat\w+)", r"forensic\w*"),
    "USAGE_RESTRICTION": (r"block[ -]?list", r"black[ -]?list", r"celebrit\w+ (filter|block\w*|detect\w*)", r"rate[ -]limit\w*"),
}

# Plain (POSIX-ERE-safe) keywords for `git log -i -G` history searches of safeguards.
SAFEGUARD_HISTORY_KEYWORDS = {
    "NSFW_FILTER": "nsfw|safety_checker|nudenet|opennsfw|nudity",
    "WATERMARK": "watermark|c2pa",
    "CONSENT_CHECK": "consent|liveness",
    "DETECTION": "deepfake.detect|fake.detect|forensic",
    "USAGE_RESTRICTION": "blocklist|blacklist|celebrit|face_whitelist",
}
CODES_BY_ID: dict[str, Code] = {c.id: c for c in ALL_CODES}

# Codes counted as an "ethics statement" for the RQ1 timeline (beneficence/legal are justification/compliance).
ETHICS_STATEMENT_CODES = ["TRANSPARENCY", "NON_MALEFICENCE", "LIABILITY_SHIFT", "CONSENT", "PRIVACY",
                          "JUSTICE_FAIRNESS", "HUMAN_CONTROL"]

# ------------------------------------------------------------------ framing hints
FRAMING_PATTERNS: dict[str, tuple[str, ...]] = {
    "liability_shift": (r"not (be )?(held )?(responsible|liable|accountable)", r"no liability", r"at (your|their) own risk",
                        r"users? (is|are|shall be|will be)( solely| fully)? responsible", r"disclaim\w*",
                        r"take no responsibility", r"without warranty", r"sole responsibility"),
    "prohibition": (r"is not (intended )?for", r"do not use", r"don'?t use", r"must not", r"shall not", r"prohibit\w*", r"forbidden",
                    r"not (be )?(allowed|permitted)", r"never use", r"should not be used", r"may not be used", r"strictly"),
    "commitment": (r"we (are )?(committed|believe|encourage|aim|strive|support|take)", r"we (have )?(added|implemented|include)",
                   r"ethical(ly)?", r"responsibl[ey]", r"to prevent", r"we (will|are going to)", r"our (goal|mission|commitment)"),
}
FRAMING_ORDER = ["liability_shift", "prohibition", "commitment"]
FRAMINGS = FRAMING_ORDER + ["descriptive", "none"]

# ------------------------------------------------------------------ issue categories (hints)
ISSUE_CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "sexual_use": (r"porn\w*", r"nsfw", r"nudes?", r"naked", r"nudity", r"sexual\w*", r"hentai", r"onlyfans", r"\bxxx\b",
                   r"explicit", r"adult content", r"uncensor\w*"),
    "ethical_concern": (r"ethic\w*", r"consent\w*", r"misuse", r"abus\w+", r"harm\w*", r"illegal", r"victims?",
                        r"non-?consensual", r"revenge", r"harass\w*", r"immoral", r"dangerous"),
    "data_practice": (r"dataset", r"training data", r"bias(ed)?", r"demographic\w*", r"skin tones?", r"balanced?",
                      r"celeba", r"ffhq", r"under-?represent\w*", r"pretrained on", r"trained on"),
    "quality_complaint": (r"bad", r"poor", r"artifacts?", r"doesn'?t work", r"not work\w*", r"wrong", r"weird", r"glitch\w*",
                          r"blurr?y?", r"quality", r"worse", r"fails?", r"error", r"robotic", r"sounds? like"),
    "feature_request": (r"feature", r"request", r"please add", r"would be (nice|great)", r"option", r"could you",
                        r"support for", r"how (to|can|do)", r"possible to", r"add (a|an)"),
}
ISSUE_CATEGORY_ORDER = ["sexual_use", "ethical_concern", "data_practice", "quality_complaint", "feature_request"]
ISSUE_CATEGORIES = ISSUE_CATEGORY_ORDER + ["other"]

DEFAULT_STATUSES = ["on", "off", "optional", "unclear"]

# Repo-level coding columns (filled by coders in S5, aggregated automatically in S4).
def repo_level_columns() -> list[str]:
    cols = [f"stated_{c.id}" for c in STATED]
    for s in SAFEGUARDS:
        cols += [f"enacted_{s.id}", f"default_{s.id}"]
    cols += ["gendered_harm_ack", "data_demographics_documented", "gender_as_feature"]
    return cols


def column_choices(col: str) -> list[str]:
    """Allowed values of a repo-level column (Excel dropdown and validation)."""
    if col.startswith("default_"):
        return DEFAULT_STATUSES + ["NA"]
    return ["yes", "no"]


# ------------------------------------------------------------------ regex helpers
def _wrap(p: str) -> str:
    # Boundaries treat "_" as a separator (unlike \b), so identifiers like is_male match.
    p = p.removeprefix(r"\b").removesuffix(r"\b")
    return rf"(?<![A-Za-z0-9])(?:{p})(?![A-Za-z0-9])"


@lru_cache(maxsize=None)
def compile_patterns(patterns: tuple[str, ...]) -> re.Pattern[str]:
    """Compile a keyword tuple into one case-insensitive alternation.

    Underscore counts as a separator, so `nsfw_filter` matches `nsfw\\w*` and `enable_nsfw` matches `nsfw\\w*`.
    """
    return re.compile("|".join(_wrap(p) for p in patterns), re.IGNORECASE)


def find_keywords(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Return all keyword matches (lower-cased) of `patterns` in `text`."""
    return [m.group(0).lower() for m in compile_patterns(patterns).finditer(text)]


def framing_hint(sentence: str) -> str:
    """Heuristic framing of a stated-value sentence."""
    for f in FRAMING_ORDER:
        if compile_patterns(FRAMING_PATTERNS[f]).search(sentence):
            return f
    return "descriptive"


def issue_category_hint(text: str) -> str:
    for cat in ISSUE_CATEGORY_ORDER:
        if compile_patterns(ISSUE_CATEGORY_PATTERNS[cat]).search(text):
            return cat
    return "other"
