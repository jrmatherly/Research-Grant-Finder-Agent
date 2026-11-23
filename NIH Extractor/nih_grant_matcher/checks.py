from __future__ import annotations
import re
from itertools import accumulate
from typing import Sequence
from .models import Fact, Finding
from .provenance import share
from .prose import scan
from .rules import Limit, PageFormat, SectionRule

_PLACEHOLDER = re.compile(r"\[NEEDS INPUT:[^\]]*\]")
_CITATION = re.compile(r"\[@([^\]\s]+)\]")
_CITATION_LIKE = re.compile(r"(?P<doi>10\.\d{4,9}/\S+)|PMID:?\s*(?P<pmid>\d+)|(?P<author>[A-Z][a-z]+) et al\.?,? \(?(?P<year>\d{4})\)?")
_FIGURE = re.compile(r"!\[|<img|^[ \t]*(?:Figure|Table)[ \t]+\d", re.M)
_URL = re.compile(r"\bhttps?://\S+|\bwww\.\S+", re.I)
_FIRST_PERSON = re.compile(r"\b(?:I|[Ww]e|[Mm]y|[Oo]ur)\b")
_NUMBER = re.compile(r"(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)%?")
_ABBREVIATION = re.compile(r"\b(?:e\.g|i\.e|et al|vs|Fig|Dr|U\.S|[A-Z])\.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_LABEL = r"(?:(?:[A-Za-z]|\d+)[.)]\s*)?"

def _sentences(text: str) -> list[str]:
    # The period after an abbreviation becomes a NUL, so the split cannot see it.
    return [s for s in _SENTENCE_END.split(_ABBREVIATION.sub(lambda m: m.group()[:-1] + "\0", text.strip())) if s.strip()]

def estimate(text: str, unit: str, page: PageFormat) -> float:
    if unit == "sentences":
        return float(len(_sentences(text)))
    lines = sum(max(1, -(-len(line) // page.chars_per_line)) for line in text.strip().splitlines())
    return {"pages": lines / page.lines_per_page, "lines": float(lines)}[unit]

def _from(text: str, at: int) -> str:
    return text[at:].split("\n", 1)[0][:80].strip()

def _numbers(text: str) -> list[str]:
    return [n for n in _NUMBER.findall(text) if "." in n or "%" in n or sum(c.isdigit() for c in n) >= 2]

def check_section(text: str, rule: SectionRule, limit: Limit, page: PageFormat, facts: Sequence[Fact], grounding: str, words: Sequence[tuple[str, str]]) -> tuple[Finding, ...]:
    references = [f for f in facts if f.kind == "reference" and f.retired_at is None]
    findings = [Finding("placeholder", "error", "The draft needed a fact from you here. Replace the placeholder with the fact or cut the sentence.", m.group()) for m in _PLACEHOLDER.finditer(text)]
    findings += [Finding("missing-part", "error", f"The {part} heading is missing. Add it on a line of its own.") for part in rule.parts
                 if not any(re.fullmatch(_LABEL + re.escape(part) + r"\s*:?", line.strip(), re.I) for line in text.splitlines())]
    if not rule.figures:
        findings += [Finding("figure-not-allowed", "error", f"{rule.title} takes no figures or tables. Remove this one.", _from(text, m.start())) for m in _FIGURE.finditer(text)]
    labels = {f.label for f in references}
    findings += [Finding("unknown-citation", "error", f"The citation [@{key}] names no reference you listed. Add the reference to your facts or remove the citation.", f"[@{key}]")
                 for key in dict.fromkeys(m.group(1) for m in _CITATION.finditer(text) if m.group(1) not in labels)]
    joined, starts = " ".join(w for w, _ in words), list(accumulate((len(w) + 1 for w, _ in words), initial=0))
    sources = [" ".join((f.text, f.label, *map(str, f.detail.values()))).lower() for f in references]
    unmatched: dict[str, None] = {}
    for m in _CITATION_LIKE.finditer(joined):
        by_model = any(origin != "applicant" and start < m.end() and start + len(word) > m.start() for start, (word, origin) in zip(starts, words))
        keys = [m["doi"].rstrip(".,;:)]").lower()] if m["doi"] else [m["pmid"]] if m["pmid"] else [m["author"].lower(), m["year"]]
        if by_model and not any(all(k in source for k in keys) for source in sources):
            unmatched[m.group()] = None
    findings += [Finding("unknown-citation", "error", "A model wrote this citation and it matches no reference you listed. Add the reference to your facts or remove the citation.", c) for c in unmatched]
    count, amount = estimate(text, limit.unit, page), f"{limit.amount:g}"
    figure = f"{count:.1f}" if limit.unit == "pages" else f"{count:g}"
    if limit.unit == "sentences" and count > limit.amount:
        findings.append(Finding("over-limit", "error", f"This section has {figure} sentences and the limit is {amount}. Cut it to {amount} or fewer."))
    elif count > limit.amount:
        findings.append(Finding("over-limit", "warning", f"This section comes to about {figure} {limit.unit} against a limit of {amount}. The figure is an estimate at NIH's densest legal format, so cut the text and check the final PDF, which is the authority."))
    elif limit.unit != "sentences" and count > 0.9 * limit.amount:
        findings.append(Finding("near-limit", "warning", f"This section comes to about {figure} {limit.unit} against a limit of {amount}. The figure is an estimate at NIH's densest legal format, so check the final PDF, which is the authority, before you add more."))
    findings += [Finding("url", "warning", "NIH allows a link only where the announcement says so. Remove it unless the announcement allows one in this section.", m.group().rstrip(".,;:)]")) for m in _URL.finditer(text)]
    if not rule.first_person and (m := _FIRST_PERSON.search(text)):
        findings.append(Finding("first-person", "warning", f"{rule.title} is written in the third person. Rewrite each sentence that uses I, we, my or our.", _from(text, m.start())))
    supplied = {n.replace(",", "").rstrip("%") for n in _numbers(grounding)}
    invented = dict.fromkeys(n for word, origin in words if origin != "applicant" for n in _numbers(_CITATION.sub("", word)) if n.replace(",", "").rstrip("%") not in supplied)
    findings += [Finding("number-not-in-inputs", "warning", f"A model wrote {n}, and that number is in nothing you supplied. Check it against your data and correct it or remove it.", n) for n in invented]
    if (written := share(words).written_share) > 0.5:
        findings.append(Finding("mostly-drafted", "warning", f"A model drafted or revised {round(written * 100)}% of the words in this section. NOT-OD-25-132 says NIH will not count a section substantially developed by AI as your original idea, and the one-half line here is this tool's and not NIH's. Rewrite more of it in your own words, and know that an AI detector can still flag text a model only polished."))
    return tuple(sorted(findings + list(scan(text)), key=lambda f: f.severity != "error"))
