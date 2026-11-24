from __future__ import annotations
import hashlib, html, re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Literal
from .clients import ApiError, GrantsGovClient, NihGuideClient
from .models import Opportunity
from .normalizer import _nih_guide_url
from .rules import GRANT_TYPES, Limit

SECTION_TITLES: dict[str, str] = {"I": "Notice of Funding Opportunity Description", "II": "Award Information", "III": "Eligibility Information", "IV": "Application and Submission Information", "V": "Application Review Information", "VI": "Award Administration Information", "VII": "Agency Contacts", "VIII": "Other Information"}
_NEXT_HEADING = re.compile(r".{0,4}Section")
_FORMS_AFTER_RESEARCH_PLAN = ("PHS Human Subjects and Clinical Trials Information", "PHS Assignment Request Form")
_SECTION_KEYS = {s.title: s.key for g in GRANT_TYPES.values() for s in g.sections}
# The verb follows the title directly, so "is not limited to" does not match.
_PAGE_LIMIT = re.compile(r"\b((?i:" + "|".join(re.escape(t) for t in _SECTION_KEYS) + r")) (?:(?:is|are|must be) limited to|(?:may|must) not exceed) (\d+(?:\.\d+)?) pages?\b")
# A Grants.gov attachment can be a page that only redirects to the NIH Guide, and the Guide can answer with a few hundred bytes of a PDF.
_SHORTEST_ANNOUNCEMENT = 1000
GRANTS_FAILED = "The request to Grants.gov failed"
# The Guide text has no line breaks, so a sentence ends only at a period, and not at the one in "2.0".
_SENTENCE_END = re.compile(r"(?<!\d)\.|\.(?!\d)")

@dataclass(frozen=True)
class Announcement:
    opportunity_number: str
    text: str
    # "nih-guide" is the text of the Guide's search service, the only Guide source before the notice's page, so copies saved earlier keep a true name.
    origin: Literal["nih-guide", "nih-guide-page", "grants.gov"]
    url: str
    sha256: str
    fetched_at: datetime
    # What Grants.gov answered when the text is the Guide's, and what the notice's page answered when the text is the search service's. Neither is saved.
    grants_says: str = field(default="", compare=False)
    page_says: str = field(default="", compare=False)
    def section(self, numeral: str) -> str:
        starts = _section_starts(self.text)
        if numeral not in starts:
            return ""
        later = [at for at in starts.values() if at > starts[numeral]]
        return self.text[starts[numeral]:later[0] if later else len(self.text)]

@dataclass(frozen=True)
class Requirement:
    kind: Literal["limit", "must", "criterion"]
    text: str
    quote: str
    origin: Literal["parsed", "model"]
    section: str = ""
    limit: Limit | None = None
    confirmed: bool | None = None
    id: int = 0
    call_id: int | None = None
    def __post_init__(self) -> None:
        if (self.call_id is not None) != (self.origin == "model"):
            raise ValueError("A requirement carries a call_id exactly when a model found it")
        if (self.kind == "limit" and self.limit is None) or (self.limit is not None and not self.limit.amount > 0):
            raise ValueError("A limit needs an amount above zero")

# shortcut: assumes the eight sections come in order, as NIH's template has them. A section that is absent and that a later section names would be misread. Upgrade if an announcement is found that drops a section.
def _section_starts(text: str) -> dict[str, int]:
    starts: dict[str, int] = {}
    after = 0
    for numeral, title in SECTION_TITLES.items():
        heading = f"Section {numeral}. {title}"
        at = text.find(heading, after)
        # The table of contents runs one heading into the next.
        while at != -1 and _NEXT_HEADING.match(text, at + len(heading)):
            at = text.find(heading, at + 1)
        if at != -1:
            starts[numeral] = after = at
    return starts

class _TextParser(HTMLParser):
    BLOCKS = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul"}
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skipping = 0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skipping += 1
        elif tag in self.BLOCKS:
            self.parts.append(" ")
    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCKS:
            self.parts.append(" ")
    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)

def html_to_text(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()

def _announcement(opportunity: Opportunity, text: str, origin: Literal["nih-guide", "nih-guide-page", "grants.gov"], url: str) -> Announcement:
    return Announcement(opportunity.opportunity_number, text, origin, url, hashlib.sha256(text.encode("utf-8")).hexdigest(), datetime.now(timezone.utc).replace(tzinfo=None))

def fetch_announcement(opportunity: Opportunity, guide: NihGuideClient | None = None, grants: GrantsGovClient | None = None) -> Announcement:
    guide, grants, number = guide or NihGuideClient(), grants or GrantsGovClient(), opportunity.opportunity_number
    try:
        text, guide_ggid = guide.doctext(number)
        # The Guide can answer for an open notice without its text for some minutes.
        guide_says = "The NIH Guide gave no text for it. The Guide sometimes answers without the text for a few minutes, so a later try may get it."
    except ApiError as exc:
        text, guide_ggid, guide_says = "", "", f"The request to the NIH Guide failed ({exc})."
    # The Guide serves its text with HTML entities and no tags.
    text = html.unescape(text).replace("\xa0", " ")
    ggid = str((opportunity.raw.get("guide_item") or {}).get("ggid") or guide_ggid or ("" if opportunity.source_id.startswith("nih-guide:") else opportunity.source_id))
    try:
        page = grants.full_announcement(ggid) if ggid else ""
        grants_says = "Grants.gov has no full announcement attached." if ggid else "Grants.gov was not asked, because the record has no Grants.gov id."
    except ApiError as exc:
        page, grants_says = "", f"{GRANTS_FAILED} ({exc})."
    # Grants.gov is the official source from fiscal 2026 (NOT-OD-25-143), and its attachment can be newer than the Guide text.
    if page and len(official := html_to_text(page)) >= _SHORTEST_ANNOUNCEMENT:
        return _announcement(opportunity, official, "grants.gov", f"https://www.grants.gov/search-results-detail/{ggid}")
    if page:
        grants_says = "Grants.gov has only a link to the announcement."
    # The search service's text drops opening brackets, the break after a heading and spaces that the notice's page keeps.
    try:
        notice, page_says = html_to_text(guide.page(number)), "The notice's page in the NIH Guide does not hold its text."
    except ApiError as exc:
        notice, page_says = "", f"The request for the notice's page in the NIH Guide failed ({exc})."
    # A notice from fiscal 2026 on has no page in the Guide, and a page that does not name the notice is another page.
    if len(notice) >= _SHORTEST_ANNOUNCEMENT and number in notice:
        return replace(_announcement(opportunity, notice, "nih-guide-page", _nih_guide_url(number)), grants_says=grants_says)
    if len(text.strip()) >= _SHORTEST_ANNOUNCEMENT:
        return replace(_announcement(opportunity, text, "nih-guide", _nih_guide_url(number)), grants_says=grants_says, page_says=page_says)
    if text.strip():
        guide_says = f"The NIH Guide answered with only {len(text.strip())} characters, too few to be the announcement."
    raise ApiError(f"No announcement text for {number}. {guide_says} {page_says} {grants_says}")

def letters(text: str) -> str:
    return re.sub(r"[\W_]", "", text)

# Copies saved from the Guide's search service lack opening brackets and spaces that the notice's page and Grants.gov keep, so a quote is compared on letters and digits.
def quoted_in(quote: str, text: str) -> bool:
    return letters(quote) in letters(text)

def _sentence_around(text: str, start: int, end: int) -> str:
    before = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    after = _SENTENCE_END.search(text, end)
    return text[before[-1] if before else 0:after.end() if after else len(text)].strip()

def parse_requirements(announcement: Announcement) -> tuple[Requirement, ...]:
    part = announcement.section("IV")
    found: list[Requirement] = []
    plan = part.rfind("PHS 398 Research Plan")
    if plan != -1:
        ends = [at for at in (part.find(form, plan) for form in _FORMS_AFTER_RESEARCH_PLAN) if at != -1]
        instructions = part[plan:min(ends, default=len(part))]
        marker = instructions.find("additional instructions:")
        if marker != -1:
            quote = instructions[marker + len("additional instructions:"):].strip()[:1500].strip()
            found.append(Requirement("must", "Follow the announcement's additional instructions for the Research Plan.", quote, "parsed", "research-strategy"))
    for match in _PAGE_LIMIT.finditer(part):
        title, pages = next(t for t in _SECTION_KEYS if t.lower() == match.group(1).lower()), float(match.group(2))
        if pages > 0:
            found.append(Requirement("limit", f"{title}: at most {pages:g} pages.", _sentence_around(part, match.start(), match.end()), "parsed", _SECTION_KEYS[title], Limit(pages, "pages")))
    return tuple(found)
