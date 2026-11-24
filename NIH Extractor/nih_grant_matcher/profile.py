from __future__ import annotations
import json, math, re
from dataclasses import asdict, dataclass, field, fields, replace
from .config import CURATED_COMPUTATIONAL_EXAMPLES, DEFAULT_KEYWORDS, INSTITUTES, MatcherConfig
from .scoring import _term_frequency

EXPORT_FORMAT = "grant-matcher-profile/1"
REFERENCE_KEY_RE = re.compile(r"[A-Za-z0-9-]+")
# focus and examples_name land in three of the six reason lines, which the dashboard renders as Markdown.
LABEL_RE = re.compile(r"[A-Za-z0-9 /,'-]{1,60}")
TEXT_FIELDS = ("investigator", "institution", "career_stage", "research_summary", "focus", "examples_name", "expertise", "resources")
# This tool's limits. They hold the text fields and the sentences to about 5,000 words together before any of it reaches a prompt.
TEXT_LIMITS = {"investigator": 200, "institution": 200, "career_stage": 200, "research_summary": 6000, "expertise": 6000, "resources": 6000}
MAX_KEYWORD, MAX_SENTENCE, MAX_REFERENCES, MAX_CITATION, MAX_INSTITUTES = 80, 600, 100, 1000, 3
# Words that say what a study does and not what it is about. As suggested terms they matched the most records ("Matched profile terms: test, how").
ACTION_WORDS = frozenset("""test tests define defines determine determines whether how identify identifies evaluate evaluates
map maps after two three examine examines assess assesses investigate investigates characterize characterizes understand
establish compare explore quantify measure reveal demonstrate among during between within which what why""".split())

class ProfileError(ValueError):
    pass

@dataclass(frozen=True)
class Reference:
    key: str
    citation: str
    pmid: str = ""
    doi: str = ""

@dataclass(frozen=True)
class Profile:
    investigator: str = ""
    institution: str = ""
    career_stage: str = ""
    research_summary: str = ""
    keywords: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_KEYWORDS))
    examples: tuple[str, ...] = CURATED_COMPUTATIONAL_EXAMPLES
    focus: str = "computational"
    examples_name: str = "curated ML/data-science grant examples"
    expertise: str = ""
    resources: str = ""
    prior_work: tuple[Reference, ...] = ()
    institutes: tuple[str, ...] = ()
    def matcher_config(self, base: MatcherConfig | None = None) -> MatcherConfig:
        return replace(base or MatcherConfig(), keywords=dict(self.keywords), semantic_examples=self.examples, focus=self.focus, examples_name=self.examples_name, institutes=self.institutes)

BUILTIN_PROFILE = Profile()

def ranks_like_builtin(profile: Profile) -> bool:
    # A keyword's place is its place in matched_terms, so the order counts.
    return list(profile.keywords.items()) == list(BUILTIN_PROFILE.keywords.items()) and (profile.examples, profile.focus, profile.examples_name, profile.institutes) == (BUILTIN_PROFILE.examples, BUILTIN_PROFILE.focus, BUILTIN_PROFILE.examples_name, BUILTIN_PROFILE.institutes)

def to_export(profile: Profile) -> str:
    # A profile with no institute leaves the key out, so that its export still imports into version 0.2.0.
    data = {name: value for name, value in asdict(profile).items() if name != "institutes" or value}
    # No sort_keys: a keyword's place in the dictionary is its place in matched_terms.
    return json.dumps({"format": EXPORT_FORMAT, "profile": {name: data[name] for name in sorted(data)}})

def from_export(text: str) -> Profile:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProfileError(f"format: the file is not JSON ({exc})") from exc
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ProfileError(f"format: expected {EXPORT_FORMAT}")
    raw = data.get("profile")
    if not isinstance(raw, dict):
        raise ProfileError("profile: expected an object")
    unknown = sorted(set(raw) - set(Profile.__dataclass_fields__))
    if unknown:
        raise ProfileError(f"{unknown[0]}: not a profile field")
    for name in TEXT_FIELDS:
        if not isinstance(raw.get(name, ""), str):
            raise ProfileError(f"{name}: expected text")
        if name in TEXT_LIMITS and len(raw.get(name, "")) > TEXT_LIMITS[name]:
            raise ProfileError(f"{name}: at most {TEXT_LIMITS[name]:,} characters")
    for name in ("focus", "examples_name"):
        if name in raw and not LABEL_RE.fullmatch(raw[name]):
            raise ProfileError(f"{name}: expected 1 to 60 letters, digits, spaces or / , ' - on one line")
    keywords = raw.get("keywords")
    if not isinstance(keywords, dict) or not 1 <= len(keywords) <= 200:
        raise ProfileError("keywords: expected an object of 1 to 200 terms")
    for term, weight in keywords.items():
        if not term.strip() or term != term.strip().lower() or type(weight) is not int or not 1 <= weight <= 30:
            raise ProfileError(f"keywords: {term!r} needs a lower-case name with no outer spaces and a weight from 1 to 30")
        if len(term) > MAX_KEYWORD or len(term.splitlines()) > 1:
            raise ProfileError(f"keywords: a term holds at most {MAX_KEYWORD} characters on one line")
    examples = raw.get("examples")
    if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 20 or not all(isinstance(example, str) for example in examples):
        raise ProfileError("examples: expected 1 to 20 sentences")
    if any(len(example) > MAX_SENTENCE for example in examples):
        raise ProfileError(f"examples: a sentence holds at most {MAX_SENTENCE} characters")
    references = raw.get("prior_work", ())
    reference_fields = {item.name for item in fields(Reference)}
    if not isinstance(references, (list, tuple)) or not all(isinstance(ref, dict) and {"key", "citation"} <= set(ref) <= reference_fields and all(isinstance(value, str) for value in ref.values()) for ref in references):
        raise ProfileError("prior_work: expected references with a key and a citation")
    if len(references) > MAX_REFERENCES:
        raise ProfileError(f"prior_work: at most {MAX_REFERENCES} references")
    for ref in references:
        if not REFERENCE_KEY_RE.fullmatch(ref["key"]):
            raise ProfileError(f"prior_work: the key {ref['key']!r} may hold only letters, digits and hyphens")
        if not ref["citation"].strip():
            raise ProfileError(f"prior_work: the key {ref['key']!r} needs a citation")
        if len(ref["citation"]) > MAX_CITATION:
            raise ProfileError(f"prior_work: the citation of {ref['key']!r} holds more than {MAX_CITATION:,} characters")
    # A later stage cites a reference by its key, so a key names one reference.
    keys = [ref["key"] for ref in references]
    if len(set(keys)) < len(keys):
        raise ProfileError(f"prior_work: the key {next(key for key in keys if keys.count(key) > 1)!r} names two references")
    institutes = raw.get("institutes", ())
    if not isinstance(institutes, (list, tuple)) or not all(isinstance(code, str) for code in institutes):
        raise ProfileError("institutes: expected a list of institute codes")
    if len(institutes) > MAX_INSTITUTES:
        raise ProfileError(f"institutes: at most {MAX_INSTITUTES} institutes")
    for code in institutes:
        if code not in INSTITUTES:
            raise ProfileError(f"institutes: {code!r} is not the code of an NIH institute")
        if institutes.count(code) > 1:
            raise ProfileError(f"institutes: {code!r} is listed twice")
    return Profile(**{**raw, "keywords": dict(keywords), "examples": tuple(examples), "prior_work": tuple(Reference(**ref) for ref in references), "institutes": tuple(institutes)})

def suggest_terms(sentences: tuple[str, ...], document_frequency: dict[str, int], documents: int, limit: int = 25) -> dict[str, int]:
    words = {token for sentence in sentences for token in _term_frequency(sentence)} - ACTION_WORDS
    # A word in more than 10 percent of NIH Guide records says nothing about the applicant.
    kept = sorted((word for word in words if document_frequency.get(word, 0) <= documents * 0.1), key=lambda word: (document_frequency.get(word, 0), word))[:limit]
    floor, ceiling = math.log((documents + 1) / (documents * 0.1 + 1)), math.log(documents + 1)
    # A word the table lacks would get the top weight, and is as often a misspelling or a word too new to count as a rare one.
    return {word: round(4 + 14 * (math.log((documents + 1) / (document_frequency[word] + 1)) - floor) / ((ceiling - floor) or 1.0)) if document_frequency.get(word) else 10 for word in kept}
