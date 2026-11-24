from __future__ import annotations
import re
from bisect import bisect_left, bisect_right
from itertools import accumulate
from typing import Sequence
from .models import Fact, Finding
from .provenance import share
from .prose import scan
from .rules import Limit, PageFormat, SectionRule

# A model can write the placeholder in another case, with a space after the bracket, or without the colon.
_PLACEHOLDER = re.compile(r"\[\s*NEEDS INPUT[^\]]*\]", re.I)
_CITATION = re.compile(r"\[@([^\]\s]+)\]")
# The author is the whole surname, so McDonald is not read as Donald. shortcut: capital and small letters are told apart in Latin-1 only, so a surname that ends in a letter such as ć is not read. Upgrade if such a citation is missed.
_SURNAME = r"[^\W\d_a-zß-öø-ÿ](?:[^\W\d_]|['-]){0,40}[a-zß-öø-ÿ]"
_CITATION_LIKE = re.compile(rf"(?P<doi>10\.\d{{4,9}}/\S+)|(?i:PMID):?\s*(?P<pmid>\d+)|\b(?P<author>{_SURNAME})(?: et al\.?,? \(?| and {_SURNAME}(?: \(|, ))(?P<year>\d{{4}}[a-z]?)\)?|\((?P<lone>{_SURNAME}), (?P<lone_year>\d{{4}}[a-z]?)\)")
_DOI, _PMID = re.compile(r"10\.\d{4,9}/\S+"), re.compile(r"PMID:?\s*(\d+)", re.I)
_PMID_FIELD = re.compile(r"\s*(?:PMID:?\s*)?(\d+)\s*", re.I)
_FIGURE = re.compile(r"!\[|<img|^[ \t]*(?:Figure|Table)[ \t]+\d", re.M)
_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)
# A roman numeral after one of these words is not the pronoun.
_FIRST_PERSON = re.compile(r"\b(?:" + "".join(f"(?<!(?i:{w}) )" for w in ("phase", "aim", "type", "class", "stage", "grade", "part")) + r"I|[Ww]e|[Mm]y|[Oo]ur)\b")
_NUMBER = re.compile(r"(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)%?")
_TITLES = r"e\.g|i\.e|et al|vs|Fig|Dr|Prof|St|Mr|Mrs|Ms|Mt|Jr|Sr|No|Inc|U\.S"
_ABBREVIATION, _TITLE = re.compile(rf"\b(?:{_TITLES}|[A-Z])\."), re.compile(rf"\b(?:{_TITLES})\.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
# For the high count, which leaves a single capital unguarded, a sentence also ends after a closing quote or bracket and before a lower-case word or a digit.
_ANY_SENTENCE_END = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s+(?=[A-Za-z0-9])")
_LABEL = r"(?:(?:[A-Za-z]|\d+)[.)]\s*)?"

def _sentences(text: str, abbreviation: re.Pattern[str] = _ABBREVIATION, end: re.Pattern[str] = _SENTENCE_END) -> list[str]:
    # The period after an abbreviation becomes a NUL, so the split cannot see it.
    return [s for s in end.split(abbreviation.sub(lambda m: m.group()[:-1] + "\0", text.strip())) if s.strip()]

def estimate(text: str, unit: str, page: PageFormat) -> float:
    if unit == "sentences":
        return float(len(_sentences(text)))
    lines = sum(max(1, -(-len(line) // page.chars_per_line)) for line in text.strip().splitlines())
    return {"pages": lines / page.lines_per_page, "lines": float(lines)}[unit]

def _from(text: str, at: int) -> str:
    return text[at:].split("\n", 1)[0][:80].strip()

def _numbers(text: str) -> list[str]:
    return [n for n in _NUMBER.findall(text) if "." in n or "%" in n or sum(c.isdigit() for c in n) >= 2]

def _trimmed(doi: str) -> str:
    # A DOI ends before what closes a wrapper or a sentence, and a ")" is its own only while it closes a "(" in it.
    while doi and (doi[-1] in ".,;:\"'>}]" or doi[-1] == ")" and doi.count(")") > doi.count("(")):
        doi = doi[:-1]
    return doi

def _doi(found: str) -> str:
    return _trimmed(found).lower()

def _field_pmid(reference: Fact) -> list[str]:
    # The field is a PMID only as a whole, so a PubMed Central ID or a list of numbers is not read as one.
    return [m[1]] if (m := _PMID_FIELD.fullmatch(str(reference.detail.get("pmid", "")))) else []

def _cites(m: re.Match[str], reference: Fact) -> bool:
    if m["doi"]:
        return _doi(m["doi"]) in set(map(_doi, _DOI.findall(f"{reference.detail.get('doi', '')} {reference.text}")))
    if m["pmid"]:
        return m["pmid"] in {*_field_pmid(reference), *_PMID.findall(reference.text)}
    author, year = (m["author"], m["year"]) if m["author"] else (m["lone"], m["lone_year"])
    year = year if year[-1].isalpha() else year + "[a-z]?"
    return all(re.search(rf"\b{k}\b", reference.text, re.I) for k in (re.escape(author), year))

def identifiers(reference: Fact) -> tuple[str, str]:
    # The profile's prior work keeps the PMID and DOI in detail, and a reference typed under Your inputs keeps them in its text.
    pmid = _field_pmid(reference) or _PMID.findall(reference.text)
    doi = _DOI.findall(f"{reference.detail.get('doi', '')} {reference.text}")
    # NCBI keys its record by the PMID without leading zeros, so a padded one would never be found.
    return (pmid[0].lstrip("0") if pmid else "", _trimmed(doi[0]) if doi else "")

def not_in_crossref(doi_id: str) -> str:
    # Crossref answers 404 for a real work that another agency registered, so its silence does not mean the work does not exist.
    return f"Crossref holds no record for {doi_id}. A DOI registered elsewhere, such as an arXiv or Zenodo DOI, which DataCite registers, is not in Crossref. Check the identifier."

def _unverified(reference: Fact) -> str:
    key, lookup = f"[@{reference.label}]", reference.detail.get("lookup")
    if lookup and lookup.get("service") == "Crossref":
        return f"{not_in_crossref(lookup.get('id'))[:-1]} that the reference {key} gives, or remove the citation."
    if lookup:
        return f"{lookup.get('service')} has no record of {lookup.get('id')}, which the reference {key} gives. Check the identifier and that the work exists, or remove the citation."
    if not any(identifiers(reference)):
        return f"The reference {key} has no PMID or DOI, so Grant Matcher cannot check that it exists. Check it yourself before you sign off."
    return f"Grant Matcher has not yet checked that the reference {key} exists. Choose Check that each reference exists under Your inputs, or run apply verify."

def check_section(text: str, rule: SectionRule, limit: Limit, page: PageFormat, facts: Sequence[Fact], grounding: str, words: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    references = [f for f in facts if f.kind == "reference" and f.retired_at is None]
    findings = [Finding("placeholder", "error", "The draft needed an input from you here. Replace the placeholder with what it asks for or cut the sentence.", m.group()) for m in _PLACEHOLDER.finditer(text)]
    findings += [Finding("missing-part", "error", f"The {part} heading is missing. Add it on a line of its own.") for part in rule.parts
                 if not any(re.fullmatch(_LABEL + re.escape(part) + r"\s*:?", line.strip(), re.I) for line in text.splitlines())]
    if not rule.figures:
        findings += [Finding("figure-not-allowed", "error", f"{rule.title} takes no figures or tables. Remove this one.", _from(text, m.start())) for m in _FIGURE.finditer(text)]
    labels = {f.label for f in references}
    findings += [Finding("unknown-citation", "error", f"The citation [@{key}] names no reference you listed. Add the reference to your inputs or remove the citation.", f"[@{key}]")
                 for key in dict.fromkeys(m.group(1) for m in _CITATION.finditer(text) if m.group(1) not in labels)]
    cited = dict.fromkeys(m.group(1) for m in _CITATION.finditer(text))
    findings += [Finding("unverified-reference", "warning", _unverified(f), f"[@{f.label}]") for f in references if f.label in cited and not (f.detail.get("lookup") or {}).get("title")]
    joined, starts = " ".join(w for w, _ in words), list(accumulate((len(w) + 1 for w, _ in words), initial=0))
    unmatched: dict[str, None] = {}
    for m in _CITATION_LIKE.finditer(joined):
        by_model = any(origin != "applicant" for _, origin in words[bisect_right(starts, m.start()) - 1:bisect_left(starts, m.end())])
        if by_model and not any(_cites(m, f) for f in references):
            unmatched[m.group()] = None
    findings += [Finding("unknown-citation", "error", "A model wrote this citation and it matches no reference you listed. Add the reference to your inputs or remove the citation.", c) for c in unmatched]
    count, amount = estimate(text, limit.unit, page), f"{limit.amount:g}"
    figure = f"{count:.1f}" if limit.unit == "pages" else f"{count:g}"
    if limit.unit == "sentences" and count > limit.amount:
        findings.append(Finding("over-limit", "error", f"This section has {figure} sentences and the limit is {amount}. Cut it to {amount} or fewer."))
    elif limit.unit == "sentences" and (high := len(_sentences(text, _TITLE, _ANY_SENTENCE_END))) > limit.amount:
        findings.append(Finding("sentence-count-unsure", "warning", f"Grant Matcher counts {figure} sentence{'' if count == 1 else 's'} one way and {high} another, and the limit is {amount}. A single letter or an initial may have been read as an abbreviation. Count the sentences by hand."))
    elif count > limit.amount:
        findings.append(Finding("over-limit", "warning", f"This section comes to about {figure} {limit.unit} against a limit of {amount}. The figure is an estimate at NIH's densest allowed format, so cut the text and check the final PDF, which is the authority."))
    elif limit.unit != "sentences" and count > 0.9 * limit.amount:
        findings.append(Finding("near-limit", "warning", f"This section comes to about {figure} {limit.unit} against a limit of {amount}. The figure is an estimate at NIH's densest allowed format, so check the final PDF, which is the authority, before you add more."))
    findings += [Finding("url", "warning", "NIH allows a link only where the announcement says so. Remove it unless the announcement allows one in this section.", m.group().rstrip(".,;:)]")) for m in _URL.finditer(text)]
    if not rule.first_person and (m := _FIRST_PERSON.search(text)):
        findings.append(Finding("first-person", "warning", f"{rule.title} is written in the third person. Rewrite each sentence that uses I, we, my or our.", _from(text, m.start())))
    supplied = {n.replace(",", "").rstrip("%") for n in _numbers(grounding)}
    invented = dict.fromkeys(n for word, origin in words if origin != "applicant" for n in _numbers(_CITATION.sub("", word)) if n.replace(",", "").rstrip("%") not in supplied)
    findings += [Finding("number-not-in-inputs", "warning", f"A model wrote {n}, and that number is in nothing you supplied. Check it against your data and correct it or remove it.", n) for n in invented]
    if (written := share(words).written_share) > 0.5:
        findings.append(Finding("mostly-drafted", "warning", f"A model drafted or revised {round(written * 100)}% of the words in this section, and an AI detector can still flag text that a model only polished. NOT-OD-25-132 says NIH will not count a section substantially developed by AI as your original idea, and the one-half line here is this tool's and not NIH's, so rewrite more of it in your own words."))
    return tuple(sorted(findings + list(scan(text)), key=lambda f: f.severity != "error"))
