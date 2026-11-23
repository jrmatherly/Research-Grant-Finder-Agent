from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Literal
from .models import Opportunity

FACT_KINDS = ("aim", "hypothesis", "preliminary", "method", "significance", "innovation", "team", "reference", "other")

@dataclass(frozen=True)
class Limit:
    amount: float
    unit: Literal["pages", "lines", "sentences"]

@dataclass(frozen=True)
class SectionRule:
    key: str
    title: str
    limit: Limit
    needs: tuple[str, ...]
    uses: tuple[str, ...] = ()
    parts: tuple[str, ...] = ()
    figures: bool = True
    first_person: bool = True
    model: Literal["none", "edit", "draft"] = "draft"
    resubmission_only: bool = False
    guidance: str = ""

@dataclass(frozen=True)
class ReviewFactor:
    key: str
    title: str
    covers: tuple[str, ...]
    scale: Literal["1-9", "appropriate"]

@dataclass(frozen=True)
class PageFormat:
    chars_per_line: int
    lines_per_page: int

@dataclass(frozen=True)
class Source:
    url: str
    read_on: str
    says: str

@dataclass(frozen=True)
class GrantType:
    funder: str
    code: str
    title: str
    sections: tuple[SectionRule, ...]
    factors: tuple[ReviewFactor, ...]
    page: PageFormat
    sources: tuple[Source, ...]

# The Introduction answers a summary statement the tool does not hold, so a model may edit it and may not draft it.
_INTRODUCTION = SectionRule("introduction", "Introduction to Application", Limit(1, "pages"), (), model="edit", resubmission_only=True)
_AIMS = SectionRule("specific-aims", "Specific Aims", Limit(1, "pages"), ("aim", "hypothesis"), ("preliminary", "reference"), figures=False)
_STRATEGY = SectionRule("research-strategy", "Research Strategy", Limit(12, "pages"), ("aim", "significance", "innovation", "method"), ("preliminary", "team", "reference"), parts=("Significance", "Innovation", "Approach"))
_SUMMARY = SectionRule("project-summary", "Project Summary/Abstract", Limit(30, "lines"), ("aim", "method"), figures=False, first_person=False)
_NARRATIVE = SectionRule("project-narrative", "Project Narrative", Limit(3, "sentences"), ("significance",), figures=False)
_FACTORS = (ReviewFactor("importance", "Importance of the Research", ("Significance", "Innovation"), "1-9"), ReviewFactor("rigor", "Rigor and Feasibility", ("Approach",), "1-9"), ReviewFactor("expertise", "Expertise and Resources", ("Investigators", "Environment"), "appropriate"))
_SOURCES = (
    Source("https://grants.nih.gov/grants-process/write-application/how-to-apply-application-guide/page-limits", "2026-11-23", "Page dated 2026-09-30. Research Strategy is 12 pages for R01, R15, R34, RF1 and U01 and 6 pages for R03, R16 and R21. Specific Aims and the Introduction are 1 page, the Project Summary/Abstract 30 lines of text, the Project Narrative three sentences, unless the NOFO says otherwise."),
    Source("https://grants.nih.gov/grants/guide/notice-files/NOT-OD-24-010.html", "2026-11-23", "The simplified review framework for R01, R03, R15, R16, R21, R34, RF1 and U01: Importance of the Research (Significance, Innovation) scored 1-9, Rigor and Feasibility (Approach) scored 1-9, Expertise and Resources (Investigator, Environment) rated Appropriate or in need of more."),
    Source("https://grants.nih.gov/grants-process/write-application/how-to-apply-application-guide/format-attachments", "2026-11-23", "Letter paper with at least half-inch margins, no more than 15 characters per linear inch and no more than six lines per vertical inch."),
    Source("https://grants.nih.gov/funding/activity-codes", "2026-11-23", "The title of each activity code."))
# 15 characters per inch over 7.5 inches and 6 lines per inch over 10 inches: the most a legal page can hold.
_DENSEST = PageFormat(chars_per_line=112, lines_per_page=60)
_R01 = GrantType("NIH", "R01", "Research Project", (_INTRODUCTION, _AIMS, _STRATEGY, _SUMMARY, _NARRATIVE), _FACTORS, _DENSEST, _SOURCES)

def _sibling(code: str, title: str, strategy_pages: float) -> GrantType:
    return replace(_R01, code=code, title=title, sections=tuple(replace(s, limit=Limit(strategy_pages, "pages")) if s.key == "research-strategy" else s for s in _R01.sections))

GRANT_TYPES: dict[str, GrantType] = {f"NIH:{g.code}": g for g in (
    _R01, _sibling("R21", "Exploratory/Developmental Grants", 6), _sibling("R03", "Small Research Grants", 6), _sibling("R15", "Research Enhancement Awards", 12), _sibling("R16", "Research Excellence Award", 6),
    _sibling("R34", "Planning Grant", 12), _sibling("RF1", "Multi-Year Funded Research Project Grant", 12), _sibling("U01", "Research Project--Cooperative Agreements", 12))}

def grant_types_for(opportunity: Opportunity) -> tuple[GrantType, ...]:
    return tuple(GRANT_TYPES[f"NIH:{code}"] for code in dict.fromkeys(opportunity.funding_instruments) if f"NIH:{code}" in GRANT_TYPES)
