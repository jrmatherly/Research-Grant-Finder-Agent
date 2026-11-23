from __future__ import annotations
import json, sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from .models import Opportunity, ScoreBreakdown, ScoredOpportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (source_id TEXT PRIMARY KEY, opportunity_number TEXT, title TEXT NOT NULL, agency_code TEXT, agency_name TEXT, status TEXT, open_date TEXT, close_date TEXT, description TEXT, eligibility_json TEXT, funding_instruments_json TEXT, funding_categories_json TEXT, award_ceiling REAL, award_floor REAL, source_url TEXT, attachments_json TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS scores (source_id TEXT PRIMARY KEY, score REAL NOT NULL, classification TEXT NOT NULL, reasons_json TEXT NOT NULL, matched_terms_json TEXT NOT NULL, breakdown_json TEXT NOT NULL, scored_at TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES opportunities(source_id));
"""
class OpportunityStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
    def close(self) -> None:
        self.conn.close()
    def upsert_scored(self, scored: ScoredOpportunity) -> bool:
        with self.conn:
            return self._upsert(scored)
    def upsert_many(self, scored_items: Iterable[ScoredOpportunity]) -> int:
        # One transaction, so a failure part-way leaves every row as it was.
        with self.conn:
            return sum(self._upsert(scored) for scored in scored_items)
    def _upsert(self, scored: ScoredOpportunity) -> bool:
        opp = scored.opportunity
        if opp.opportunity_number:
            # One row per opportunity number. The NIH Guide record wins, as in the workflow's dedupe.
            yields = not opp.source_id.startswith("nih-guide:") and self.conn.execute("SELECT 1 FROM opportunities WHERE opportunity_number = ? AND source_id LIKE 'nih-guide:%'", (opp.opportunity_number,)).fetchone() is not None
            # A database written before this rule can hold several rows for one number, so clear them on either path.
            others, args = ("opportunity_number = ? AND source_id NOT LIKE 'nih-guide:%'", (opp.opportunity_number,)) if yields else ("opportunity_number = ? AND source_id != ?", (opp.opportunity_number, opp.source_id))
            self.conn.execute(f"DELETE FROM scores WHERE source_id IN (SELECT source_id FROM opportunities WHERE {others})", args)
            self.conn.execute(f"DELETE FROM opportunities WHERE {others}", args)
            if yields:
                return False
        self.conn.execute("""INSERT INTO opportunities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET opportunity_number=excluded.opportunity_number, title=excluded.title, agency_code=excluded.agency_code, agency_name=excluded.agency_name, status=excluded.status, open_date=excluded.open_date, close_date=excluded.close_date, description=excluded.description, eligibility_json=excluded.eligibility_json, funding_instruments_json=excluded.funding_instruments_json, funding_categories_json=excluded.funding_categories_json, award_ceiling=excluded.award_ceiling, award_floor=excluded.award_floor, source_url=excluded.source_url, attachments_json=excluded.attachments_json, raw_json=excluded.raw_json""", (opp.source_id, opp.opportunity_number, opp.title, opp.agency_code, opp.agency_name, opp.status, opp.open_date.isoformat() if opp.open_date else None, opp.close_date.isoformat() if opp.close_date else None, opp.description, json.dumps(opp.eligibility), json.dumps(opp.funding_instruments), json.dumps(opp.funding_categories), opp.award_ceiling, opp.award_floor, opp.source_url, json.dumps(opp.attachments), json.dumps(opp.raw)))
        self.conn.execute("""INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET score=excluded.score, classification=excluded.classification, reasons_json=excluded.reasons_json, matched_terms_json=excluded.matched_terms_json, breakdown_json=excluded.breakdown_json, scored_at=excluded.scored_at""", (opp.source_id, scored.score, scored.classification, json.dumps(scored.reasons), json.dumps(scored.matched_terms), json.dumps(scored.breakdown.__dict__), scored.scored_at.isoformat()))
        return True
    def top_scored(self, min_score: float = 0.0, limit: int = 50, today: date | None = None) -> list[ScoredOpportunity]:
        # Rows saved by an earlier run stay in the database after they close, so leave them out here.
        rows = self.conn.execute("""SELECT o.*, s.score, s.classification, s.reasons_json, s.matched_terms_json, s.breakdown_json, s.scored_at FROM opportunities o JOIN scores s ON s.source_id = o.source_id WHERE s.score >= ? AND (o.close_date IS NULL OR o.close_date >= ?) ORDER BY s.score DESC, o.close_date IS NULL, o.close_date ASC LIMIT ?""", (min_score, (today or date.today()).isoformat(), limit)).fetchall()
        return [self._row_to_scored(row) for row in rows]
    @staticmethod
    def _row_to_scored(row: sqlite3.Row) -> ScoredOpportunity:
        def parse_date(value: str | None) -> date | None:
            return date.fromisoformat(value) if value else None
        opp = Opportunity(source_id=row["source_id"], opportunity_number=row["opportunity_number"] or "", title=row["title"] or "", agency_code=row["agency_code"] or "", agency_name=row["agency_name"] or "", status=row["status"] or "", open_date=parse_date(row["open_date"]), close_date=parse_date(row["close_date"]), description=row["description"] or "", eligibility=tuple(json.loads(row["eligibility_json"] or "[]")), funding_instruments=tuple(json.loads(row["funding_instruments_json"] or "[]")), funding_categories=tuple(json.loads(row["funding_categories_json"] or "[]")), award_ceiling=row["award_ceiling"], award_floor=row["award_floor"], source_url=row["source_url"] or "", attachments=tuple(json.loads(row["attachments_json"] or "[]")), raw=json.loads(row["raw_json"] or "{}"))
        return ScoredOpportunity(opportunity=opp, score=row["score"], classification=row["classification"], reasons=tuple(json.loads(row["reasons_json"])), matched_terms=tuple(json.loads(row["matched_terms_json"])), breakdown=ScoreBreakdown(**json.loads(row["breakdown_json"])), scored_at=datetime.fromisoformat(row["scored_at"]))
