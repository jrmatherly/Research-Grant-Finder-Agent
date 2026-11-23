from __future__ import annotations
import json, math, re
from collections import Counter
from datetime import date, datetime, timezone
from .config import GENERIC_BIOMEDICAL_TERMS, KEYWORD_PATTERNS, TERM_RARITY_PATH, MatcherConfig
from .models import Opportunity, ScoreBreakdown, ScoredOpportunity

TOKEN_RE = re.compile(r"[a-z0-9]+")
# "AI/AN" is American Indian and Alaska Native, not artificial intelligence.
AI_WORD_RE = re.compile(r"\bai\b(?!\s*/\s*ans?\b)", re.IGNORECASE)
STOPWORDS = frozenset("a an and are as at be by for from in is it of on or that the this to use using will with".split())
def _term_frequency(text: str) -> Counter[str]:
    return Counter(token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS)
def document_frequencies(texts: list[str]) -> dict[str, int]:
    return dict(Counter(token for text in texts for token in set(_term_frequency(text))))
def _cosine(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(left[token] * right[token] for token in set(left) & set(right))
    left_norm = math.sqrt(sum(v * v for v in left.values()))
    right_norm = math.sqrt(sum(v * v for v in right.values()))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0

class MLRelevanceScorer:
    def __init__(self, config: MatcherConfig | None = None) -> None:
        self.config = config or MatcherConfig()
        # Similarity weights each word by how rare it is in NIH Guide text, so "research" and "health" count for little and "phenotypes" for a lot.
        # The table is fixed in the repository, so a record scores the same whatever else a run fetched.
        try:
            rarity = json.loads(TERM_RARITY_PATH.read_text(encoding="utf-8"))
            self.documents, self.document_frequency = rarity["documents"], rarity["terms"]
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError(f"Cannot read the word-rarity table {TERM_RARITY_PATH}. Restore it from git, or rebuild it with `python -m nih_grant_matcher rarity-table`.") from exc
        self.example_vectors = [self._weighted(example) for example in self.config.semantic_examples]
        # A keyword starts at the start of a word, so "modeling" does not match "remodeling", and may take a suffix
        # ("algorithm" matches "algorithms"). An acronym of three letters or fewer takes a plural only.
        self.keyword_patterns = {phrase: re.compile(KEYWORD_PATTERNS.get(phrase) or rf"(?<!\w){re.escape(phrase)}" + (r"\w*" if len(phrase) > 3 else r"s?(?!\w)")) for phrase in self.config.keywords}
    def _weighted(self, text: str) -> dict[str, float]:
        return {token: count * (math.log((self.documents + 1) / (self.document_frequency.get(token, 0) + 1)) + 1) for token, count in _term_frequency(text).items()}
    def _keyword_hits(self, text: str) -> list[str]:
        spans = {phrase: [match.span() for match in pattern.finditer(text)] for phrase, pattern in self.keyword_patterns.items()}
        hits, taken = set(), []
        # Words that two keywords share are one piece of evidence. The longer keyword takes them, and a shorter one counts
        # only where it also matches text that no longer keyword took: "medical imaging analytics" is "imaging analytics" alone.
        for phrase in sorted(spans, key=len, reverse=True):
            free = [(start, end) for start, end in spans[phrase] if not any(start < b and a < end for a, b in taken)]
            if free:
                hits.add(phrase)
                taken += free
        return [phrase for phrase in spans if phrase in hits]
    def score(self, opportunity: Opportunity, today: date | None = None) -> ScoredOpportunity:
        today = today or date.today()
        text = opportunity.searchable_text.lower()
        title = opportunity.title.lower()
        matched_terms, keyword_score, centrality_score = [], 0.0, 0.0
        if AI_WORD_RE.search(opportunity.searchable_text):
            matched_terms.append("AI")
            keyword_score += 18
            centrality_score += 12 if AI_WORD_RE.search(opportunity.title) else 4
        title_hits = self._keyword_hits(title)
        for phrase in self._keyword_hits(text):
            weight = self.config.keywords[phrase]
            in_title = phrase in title_hits
            matched_terms.append(phrase)
            keyword_score += weight
            centrality_score += min(weight * (0.8 if in_title else 0.25), 12 if in_title else 4)
        vector = self._weighted(opportunity.searchable_text)
        similarity, example = max(((_cosine(vector, ex), ex) for ex in self.example_vectors), key=lambda pair: pair[0], default=(0.0, {}))
        # A text of a few words is close to an example as soon as it shares one of them, so scale similarity down below 30 words.
        # NIH Guide records run from about 25 words up. A Grants.gov record with no synopsis is a title alone.
        semantic_score = min(similarity * min(1.0, sum(_term_frequency(opportunity.searchable_text).values()) / 30) * 120, 20)
        shared_terms = sorted(set(vector) & set(example), key=lambda token: -vector[token] * example[token])[:3]
        nih_score = 10.0 if self._is_nih_hhs(opportunity) else 0.0
        urgency_score = self._deadline_score(opportunity.close_date, today)
        completeness_score = self._completeness_score(opportunity)
        generic_penalty = self._generic_penalty(text, matched_terms)
        score = max(0.0, min(100.0, keyword_score + semantic_score + nih_score + urgency_score + completeness_score + min(centrality_score, 18) - generic_penalty))
        return ScoredOpportunity(opportunity=opportunity, score=round(score, 1), classification=self._classification(round(score, 1)), reasons=tuple(self._reasons(opportunity, matched_terms, semantic_score, urgency_score, generic_penalty, shared_terms)), matched_terms=tuple(matched_terms), breakdown=ScoreBreakdown(round(keyword_score, 1), round(semantic_score, 1), round(nih_score, 1), round(urgency_score, 1), round(completeness_score, 1), round(min(centrality_score, 18), 1), round(generic_penalty, 1)), scored_at=datetime.now(timezone.utc).replace(tzinfo=None))
    @staticmethod
    def _is_nih_hhs(opportunity: Opportunity) -> bool:
        combined = f"{opportunity.agency_code} {opportunity.agency_name}".lower()
        return "nih" in combined or "national institutes of health" in combined or "hhs" in combined
    @staticmethod
    def _deadline_score(close_date: date | None, today: date) -> float:
        if close_date is None:
            return 3.0
        days = (close_date - today).days
        if days < 0:
            return -20.0
        if days <= 14:
            return 4.0
        if days <= 90:
            return 8.0
        if days <= 240:
            return 6.0
        return 3.0
    @staticmethod
    def _completeness_score(opportunity: Opportunity) -> float:
        fields = [opportunity.description, opportunity.close_date, opportunity.eligibility, opportunity.funding_instruments, opportunity.funding_categories, opportunity.award_ceiling, opportunity.source_url]
        return sum(1.0 for field in fields if field) / len(fields) * 7.0
    @staticmethod
    def _generic_penalty(text: str, matched_terms: list[str]) -> float:
        generic_hits = sum(1 for term in GENERIC_BIOMEDICAL_TERMS if term in text)
        return max(0.0, generic_hits * 2.0 - len(matched_terms)) if matched_terms else generic_hits * 5.0
    @staticmethod
    def _classification(score: float) -> str:
        return "High" if score >= 70 else "Medium" if score >= 35 else "Watchlist"
    @staticmethod
    def _reasons(opportunity: Opportunity, matched_terms: list[str], semantic_score: float, urgency_score: float, generic_penalty: float, shared_terms: list[str]) -> list[str]:
        reasons = []
        if matched_terms:
            reasons.append("Matched computational terms: " + ", ".join(matched_terms[:6]))
        if semantic_score >= 8:
            reasons.append("Description is close to curated ML/data-science grant examples (shared terms: " + ", ".join(shared_terms) + ")")
        if MLRelevanceScorer._is_nih_hhs(opportunity):
            reasons.append("Source agency appears to be NIH/HHS")
        if opportunity.close_date and urgency_score > 0:
            reasons.append(f"Deadline is still active: {opportunity.close_date.isoformat()}")
        if generic_penalty > 0 and not matched_terms:
            reasons.append("Mostly generic biomedical wording; keep only as watchlist")
        return reasons or ["Weak computational signal; included for monitoring only"]
