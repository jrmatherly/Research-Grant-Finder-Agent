from __future__ import annotations
import json, math, re
from collections import Counter
from dataclasses import asdict, dataclass, field, fields, replace
from .config import CURATED_COMPUTATIONAL_EXAMPLES, DEFAULT_KEYWORDS, INSTITUTES, MatcherConfig
from .scoring import STOPWORDS, TOKEN_RE

EXPORT_FORMAT = "grant-matcher-profile/1"
REFERENCE_KEY_RE = re.compile(r"[A-Za-z0-9-]+")
# focus and examples_name land in three of the six reason lines, which the dashboard renders as Markdown.
LABEL_RE = re.compile(r"[A-Za-z0-9 /,'-]{1,60}")
TEXT_FIELDS = ("investigator", "institution", "career_stage", "research_summary", "focus", "examples_name", "expertise", "resources")
# This tool's limits. They hold the text fields and the sentences to about 5,000 words together, so that a later prompt built from them stays small.
TEXT_LIMITS = {"investigator": 200, "institution": 200, "career_stage": 200, "research_summary": 6000, "expertise": 6000, "resources": 6000}
MAX_KEYWORD, MAX_SENTENCE, MAX_REFERENCES, MAX_CITATION, MAX_INSTITUTES = 80, 600, 100, 1000, 3
# Words that say what a study does and not what it is about. As suggested terms they matched the most records ("Matched profile terms: test, how").
ACTION_WORDS = frozenset("""test tests define defines determine determines whether how identify identifies evaluate evaluates
map maps after two three examine examines assess assesses investigate investigates characterize characterizes understand
establish compare explore quantify measure reveal demonstrate among during between within which what why""".split())

# Words of general English that NIH Guide text seldom holds, so the rarity table calls them rare ("we" is in 17 of 3,000 records), and the "aim" that labels a sentence. The set also keeps these words out of a phrase, so it holds common ones too.
GENERAL_WORDS = frozenset("""we our us i my they their them its he she his her you your who whom whose so such than then there these those also both
each all any some more most other into onto over under about across through per via not no nor but if because while when where can could may
might must should would do does did has have had been being was were live lives far near find finds keep keeps reach reaches reduce reduces
improve improves adapt adapts manage manages work works aim aims""".split())

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
    # A profile with no institute leaves the key out, so that its export still imports into a release that does not know the field.
    data = {name: value for name, value in asdict(profile).items() if name != "institutes" or value}
    # No sort_keys: a keyword's place in the dictionary is its place in matched_terms.
    return json.dumps({"format": EXPORT_FORMAT, "profile": {name: data[name] for name in sorted(data)}})

# The limits are checked on a save and an import. A stored profile is read without them, since a release before the limits saved text of any length.
def from_export(text: str, limits: bool = True) -> Profile:
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
        if limits and name in TEXT_LIMITS and len(raw.get(name, "")) > TEXT_LIMITS[name]:
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
        if limits and (len(term) > MAX_KEYWORD or len(term.splitlines()) > 1):
            raise ProfileError(f"keywords: a term holds at most {MAX_KEYWORD} characters on one line")
    examples = raw.get("examples")
    if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 20 or not all(isinstance(example, str) for example in examples):
        raise ProfileError("examples: expected 1 to 20 sentences")
    if limits and any(len(example) > MAX_SENTENCE for example in examples):
        raise ProfileError(f"examples: a sentence holds at most {MAX_SENTENCE} characters")
    references = raw.get("prior_work", ())
    reference_fields = {item.name for item in fields(Reference)}
    if not isinstance(references, (list, tuple)) or not all(isinstance(ref, dict) and {"key", "citation"} <= set(ref) <= reference_fields and all(isinstance(value, str) for value in ref.values()) for ref in references):
        raise ProfileError("prior_work: expected references with a key and a citation")
    if limits and len(references) > MAX_REFERENCES:
        raise ProfileError(f"prior_work: at most {MAX_REFERENCES} references")
    for ref in references:
        if not REFERENCE_KEY_RE.fullmatch(ref["key"]):
            raise ProfileError(f"prior_work: the key {ref['key']!r} may hold only letters, digits and hyphens")
        if not ref["citation"].strip():
            raise ProfileError(f"prior_work: the key {ref['key']!r} needs a citation")
        if limits and len(ref["citation"]) > MAX_CITATION:
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
    floor, ceiling = math.log((documents + 1) / (documents * 0.1 + 1)), math.log(documents + 1)
    def weight(word: str) -> int:
        # A word in more than 10 percent of NIH Guide records says nothing about the applicant, and gets 0.
        # A word the table lacks would get the top weight, and is as often a misspelling or a word too new to count as a rare one.
        frequency = document_frequency.get(word, 0)
        return 0 if frequency > documents * 0.1 else round(4 + 14 * (math.log((documents + 1) / (frequency + 1)) - floor) / ((ceiling - floor) or 1.0)) if frequency else 10
    skip, counts, pairs = STOPWORDS | ACTION_WORDS | GENERAL_WORDS, Counter(), Counter()
    for text in (sentence.lower() for sentence in sentences):
        # The letters after an apostrophe ("parkinson's", "don't") are an ending, not a word, and would pair with the next word as "s tremor".
        found = [match for match in TOKEN_RE.finditer(text) if not match.group().isdigit() and not (match.start() > 1 and text[match.start() - 1] in "'’" and text[match.start() - 2].isalnum())]
        counts.update(match.group() for match in found)
        # A phrase is two words that a space or a hyphen joins, in the form the applicant wrote. shortcut: no phrase of three words, add one when a list shows the need.
        pairs.update(text[left.start():right.end()] for left, right in zip(found, found[1:]) if text[left.end():right.start()] in (" ", "-") and not {left.group(), right.group()} & skip)
    # The applicant's own repetition marks a phrase. Of two repeated phrases that share a word ("self-management", "management support"), the more frequent one stays.
    # A hyphen marks one by itself, and always stays. Its halves ("self", "energy" of "energy-limiting") would match every word that starts with them.
    repeated = {phrase: count for phrase, count in pairs.items() if (count >= 2 or "-" in phrase) and any(weight(word) for word in TOKEN_RE.findall(phrase))}
    phrases = {phrase: count for phrase, count in repeated.items() if "-" in phrase or not any(other != phrase and more > count and set(TOKEN_RE.findall(other)) & set(TOKEN_RE.findall(phrase)) for other, more in repeated.items())}
    inside = Counter(word for phrase, count in phrases.items() for word in TOKEN_RE.findall(phrase) for _ in range(count))
    # A word that occurs only inside a proposed phrase is not proposed again by itself.
    found = {**{phrase: (count, max(weight(word) for word in TOKEN_RE.findall(phrase))) for phrase, count in phrases.items()}, **{word: (count, weight(word)) for word, count in counts.items() if word not in skip and weight(word) and count > inside[word]}}
    # Rarity alone put the general words first and cut the field's own words ("chronic" is in 118 of 3,000 records), so the words the applicant repeats come first.
    return {term: found[term][1] for term in sorted(found, key=lambda term: (-found[term][0] * found[term][1], term))[:limit]}
