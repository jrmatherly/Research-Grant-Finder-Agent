from __future__ import annotations
import json, math, re
from dataclasses import asdict, dataclass, field, fields, replace
from .config import CURATED_COMPUTATIONAL_EXAMPLES, DEFAULT_KEYWORDS, MatcherConfig
from .scoring import _term_frequency

EXPORT_FORMAT = "grant-matcher-profile/1"
REFERENCE_KEY_RE = re.compile(r"[A-Za-z0-9-]+")
# focus and examples_name land in three of the six reason lines, which the dashboard renders as Markdown.
LABEL_RE = re.compile(r"[A-Za-z0-9 /,'-]{1,60}")
TEXT_FIELDS = ("investigator", "institution", "career_stage", "research_summary", "focus", "examples_name", "expertise", "resources")

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
    def matcher_config(self, base: MatcherConfig | None = None) -> MatcherConfig:
        return replace(base or MatcherConfig(), keywords=dict(self.keywords), semantic_examples=self.examples, focus=self.focus, examples_name=self.examples_name)

BUILTIN_PROFILE = Profile()

def to_export(profile: Profile) -> str:
    data = asdict(profile)
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
    for name in ("focus", "examples_name"):
        if name in raw and not LABEL_RE.fullmatch(raw[name]):
            raise ProfileError(f"{name}: expected 1 to 60 letters, digits, spaces or / , ' - on one line")
    keywords = raw.get("keywords")
    if not isinstance(keywords, dict) or not 1 <= len(keywords) <= 200:
        raise ProfileError("keywords: expected an object of 1 to 200 terms")
    for term, weight in keywords.items():
        if not term.strip() or term != term.strip().lower() or type(weight) is not int or not 1 <= weight <= 30:
            raise ProfileError(f"keywords: {term!r} needs a lower-case name with no outer spaces and a weight from 1 to 30")
    examples = raw.get("examples")
    if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 20 or not all(isinstance(example, str) for example in examples):
        raise ProfileError("examples: expected 1 to 20 sentences")
    references = raw.get("prior_work", ())
    reference_fields = {item.name for item in fields(Reference)}
    if not isinstance(references, (list, tuple)) or not all(isinstance(ref, dict) and {"key", "citation"} <= set(ref) <= reference_fields and all(isinstance(value, str) for value in ref.values()) for ref in references):
        raise ProfileError("prior_work: expected references with a key and a citation")
    for ref in references:
        if not REFERENCE_KEY_RE.fullmatch(ref["key"]):
            raise ProfileError(f"prior_work: the key {ref['key']!r} may hold only letters, digits and hyphens")
        if not ref["citation"].strip():
            raise ProfileError(f"prior_work: the key {ref['key']!r} needs a citation")
    # A later stage cites a reference by its key, so a key names one reference.
    keys = [ref["key"] for ref in references]
    if len(set(keys)) < len(keys):
        raise ProfileError(f"prior_work: the key {next(key for key in keys if keys.count(key) > 1)!r} names two references")
    return Profile(**{**raw, "keywords": dict(keywords), "examples": tuple(examples), "prior_work": tuple(Reference(**ref) for ref in references)})

def suggest_terms(sentences: tuple[str, ...], document_frequency: dict[str, int], documents: int, limit: int = 25) -> dict[str, int]:
    words = {token for sentence in sentences for token in _term_frequency(sentence)}
    # A word in more than 10 percent of NIH Guide records says nothing about the applicant.
    kept = sorted((word for word in words if document_frequency.get(word, 0) <= documents * 0.1), key=lambda word: (document_frequency.get(word, 0), word))[:limit]
    floor, ceiling = math.log((documents + 1) / (documents * 0.1 + 1)), math.log(documents + 1)
    return {word: round(4 + 14 * (math.log((documents + 1) / (document_frequency.get(word, 0) + 1)) - floor) / ((ceiling - floor) or 1.0)) for word in kept}
