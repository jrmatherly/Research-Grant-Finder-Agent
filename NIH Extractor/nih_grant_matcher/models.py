from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal, Protocol

@dataclass(frozen=True)
class Opportunity:
    source_id: str
    opportunity_number: str
    title: str
    agency_code: str
    agency_name: str
    status: str
    open_date: date | None = None
    close_date: date | None = None
    description: str = ""
    eligibility: tuple[str, ...] = ()
    funding_instruments: tuple[str, ...] = ()
    funding_categories: tuple[str, ...] = ()
    award_ceiling: float | None = None
    award_floor: float | None = None
    source_url: str = ""
    attachments: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)
    @property
    def searchable_text(self) -> str:
        parts = [self.title, self.description, " ".join(self.eligibility), " ".join(self.funding_instruments), " ".join(self.funding_categories), self.agency_name]
        return "\n".join(p for p in parts if p)

@dataclass(frozen=True)
class ScoreBreakdown:
    keyword_score: float
    semantic_score: float
    nih_score: float
    urgency_score: float
    completeness_score: float
    centrality_score: float
    generic_penalty: float
    institute_score: float = 0.0

@dataclass(frozen=True)
class ScoredOpportunity:
    opportunity: Opportunity
    score: float
    classification: str
    reasons: tuple[str, ...]
    matched_terms: tuple[str, ...]
    breakdown: ScoreBreakdown
    scored_at: datetime

@dataclass(frozen=True)
class Finding:
    code: str
    severity: Literal["error", "warning"]
    message: str
    excerpt: str = ""

@dataclass(frozen=True)
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    truncated: bool

class Model(Protocol):
    provider: str
    name: str
    host: str
    def complete(self, system: str, user: str, max_tokens: int = 16000) -> Completion: ...

@dataclass(frozen=True)
class Application:
    id: int
    opportunity_number: str
    grant_type: str
    title: str
    resubmission: bool
    disclosure_on: bool
    created_at: datetime

@dataclass(frozen=True)
class Fact:
    id: int
    kind: str
    text: str
    label: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    retired_at: datetime | None = None

@dataclass(frozen=True)
class ModelCall:
    id: int
    section: str
    purpose: str
    provider: str
    model: str
    system: str
    prompt: str
    response: str
    input_tokens: int
    output_tokens: int
    created_at: datetime
    parent_id: int | None = None

@dataclass(frozen=True)
class Revision:
    id: int
    section: str
    parent_id: int | None
    author: Literal["applicant", "model"]
    action: Literal["write", "polish", "revise", "draft"]
    text: str
    call_id: int | None
    created_at: datetime

@dataclass(frozen=True)
class Signoff:
    section: str
    revision_id: int
    signer: str
    attestation: str
    findings: tuple[str, ...]
    tool_version: str
    signed_at: datetime

@dataclass(frozen=True)
class ReviewPoint:
    factor: str
    kind: Literal["strength", "weakness", "prose"]
    text: str
    quote: str

@dataclass(frozen=True)
class Review:
    revision_id: int
    scores: dict[str, int | str]
    points: tuple[ReviewPoint, ...]
    model: str
    # The points of the reply that Grant Matcher dropped, so the applicant knows the model said more.
    dropped: int = 0

@dataclass(frozen=True)
class Attribution:
    applicant_words: int
    written_words: int
    polished_words: int
    @property
    def model_words(self) -> int:
        return self.written_words + self.polished_words
    @property
    def written_share(self) -> float:
        return self.written_words / (self.applicant_words + self.model_words or 1)
    @property
    def polished_share(self) -> float:
        return self.polished_words / (self.applicant_words + self.model_words or 1)
