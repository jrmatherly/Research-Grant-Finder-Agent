from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from .announcement import Announcement, Requirement
from .models import Application, Fact, ModelCall, Opportunity, Review, ReviewPoint, Revision, ScoreBreakdown, ScoredOpportunity, Signoff
from .profile import BUILTIN_PROFILE, Profile, ProfileError, from_export, to_export
from .rules import Limit

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (source_id TEXT PRIMARY KEY, opportunity_number TEXT, title TEXT NOT NULL, agency_code TEXT, agency_name TEXT, status TEXT, open_date TEXT, close_date TEXT, description TEXT, eligibility_json TEXT, funding_instruments_json TEXT, funding_categories_json TEXT, award_ceiling REAL, award_floor REAL, source_url TEXT, attachments_json TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS scores (source_id TEXT PRIMARY KEY, score REAL NOT NULL, classification TEXT NOT NULL, reasons_json TEXT NOT NULL, matched_terms_json TEXT NOT NULL, breakdown_json TEXT NOT NULL, scored_at TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES opportunities(source_id));
CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), profile_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS announcements (opportunity_number TEXT PRIMARY KEY, text TEXT NOT NULL, origin TEXT NOT NULL, url TEXT NOT NULL, sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications (id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_number TEXT NOT NULL, grant_type TEXT NOT NULL, title TEXT NOT NULL, resubmission INTEGER NOT NULL DEFAULT 0, disclosure_on INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, UNIQUE (opportunity_number, grant_type, resubmission));
CREATE TABLE IF NOT EXISTS facts (id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES applications(id), kind TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', text TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, retired_at TEXT);
-- A call's parent_id is checked at commit, because delete_application removes the revisions before the calls that name them.
CREATE TABLE IF NOT EXISTS model_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, application_id INTEGER NOT NULL REFERENCES applications(id), section TEXT NOT NULL DEFAULT '', purpose TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, system TEXT NOT NULL, prompt TEXT NOT NULL, response TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, parent_id INTEGER REFERENCES revisions(id) DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE IF NOT EXISTS requirements (id INTEGER PRIMARY KEY AUTOINCREMENT, application_id INTEGER NOT NULL REFERENCES applications(id), section TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, text TEXT NOT NULL, quote TEXT NOT NULL, limit_json TEXT, origin TEXT NOT NULL CHECK (origin IN ('parsed', 'model')), call_id INTEGER REFERENCES model_calls(id), confirmed INTEGER, CHECK ((origin = 'model') = (call_id IS NOT NULL)));
CREATE TABLE IF NOT EXISTS revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, application_id INTEGER NOT NULL REFERENCES applications(id), section TEXT NOT NULL, parent_id INTEGER REFERENCES revisions(id), author TEXT NOT NULL CHECK (author IN ('applicant', 'model')), action TEXT NOT NULL CHECK (action IN ('write', 'polish', 'revise', 'draft')), text TEXT NOT NULL, call_id INTEGER UNIQUE REFERENCES model_calls(id), created_at TEXT NOT NULL, CHECK ((author = 'model') = (call_id IS NOT NULL)), CHECK ((author = 'applicant') = (action = 'write')));
CREATE TABLE IF NOT EXISTS signoffs (id INTEGER PRIMARY KEY AUTOINCREMENT, application_id INTEGER NOT NULL REFERENCES applications(id), section TEXT NOT NULL, revision_id INTEGER NOT NULL REFERENCES revisions(id), signer TEXT NOT NULL, attestation TEXT NOT NULL, findings_json TEXT NOT NULL, tool_version TEXT NOT NULL, signed_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS revisions_fixed BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT, 'revisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS revisions_stay BEFORE DELETE ON revisions WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = 'deleting' AND value = CAST(OLD.application_id AS TEXT)) BEGIN SELECT RAISE(ABORT, 'revisions is append-only'); END;
CREATE TRIGGER IF NOT EXISTS model_calls_fixed BEFORE UPDATE ON model_calls BEGIN SELECT RAISE(ABORT, 'model_calls is append-only'); END;
CREATE TRIGGER IF NOT EXISTS model_calls_stay BEFORE DELETE ON model_calls WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = 'deleting' AND value = CAST(OLD.application_id AS TEXT)) BEGIN SELECT RAISE(ABORT, 'model_calls is append-only'); END;
CREATE TRIGGER IF NOT EXISTS signoffs_fixed BEFORE UPDATE ON signoffs BEGIN SELECT RAISE(ABORT, 'signoffs is append-only'); END;
CREATE TRIGGER IF NOT EXISTS signoffs_stay BEFORE DELETE ON signoffs WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = 'deleting' AND value = CAST(OLD.application_id AS TEXT)) BEGIN SELECT RAISE(ABORT, 'signoffs is append-only'); END;
CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES applications(id), revision_id INTEGER NOT NULL REFERENCES revisions(id), call_id INTEGER NOT NULL REFERENCES model_calls(id), review_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS reviews_fixed BEFORE UPDATE ON reviews BEGIN SELECT RAISE(ABORT, 'reviews is append-only'); END;
CREATE TRIGGER IF NOT EXISTS reviews_stay BEFORE DELETE ON reviews WHEN NOT EXISTS (SELECT 1 FROM settings WHERE key = 'deleting' AND value = CAST(OLD.application_id AS TEXT)) BEGIN SELECT RAISE(ABORT, 'reviews is append-only'); END;
"""
class ReadOnlyDatabase(sqlite3.DatabaseError):
    pass
class ReadOnlyProfile(ProfileError):
    pass
def _now() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
def _time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
class OpportunityStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        try:
            self.conn.executescript(SCHEMA)
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            # A read-only database from an earlier version lacks the newer tables, and each of them then reads as empty.
            if exc.sqlite_errorcode & 0xFF != sqlite3.SQLITE_READONLY:
                raise
    def close(self) -> None:
        self.conn.close()
    def _has(self, table: str) -> bool:
        return self.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None
    def _rows(self, table: str, sql: str, args: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, args).fetchall() if self._has(table) else []
    @contextmanager
    def _write(self, table: str, error: type[Exception] = ReadOnlyDatabase) -> Iterator[None]:
        # SCHEMA creates every table on open, so a table is missing only from a read-only database that an earlier version wrote.
        if not self._has(table):
            raise error(f"{self.db_path} was written by an earlier version and is read-only, so it has no {table} table to save to. Open a copy you can write to.")
        with self.conn:
            yield
    def profile(self) -> Profile:
        row = self.conn.execute("SELECT profile_json FROM profile WHERE id = 1").fetchone() if self._has("profile") else None
        return from_export(row["profile_json"], limits=False) if row else BUILTIN_PROFILE
    def save_profile(self, profile: Profile | None) -> None:
        if profile is not None:
            text = to_export(profile)
            from_export(text)
        with self._write("profile", ReadOnlyProfile):
            if profile is None:
                self.conn.execute("DELETE FROM profile")
            else:
                self.conn.execute("INSERT INTO profile VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at", (text, datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
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
        # A release that does not know institute_score rebuilds the breakdown from these keys, so a row with no institute bonus leaves it out.
        self.conn.execute("""INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET score=excluded.score, classification=excluded.classification, reasons_json=excluded.reasons_json, matched_terms_json=excluded.matched_terms_json, breakdown_json=excluded.breakdown_json, scored_at=excluded.scored_at""", (opp.source_id, scored.score, scored.classification, json.dumps(scored.reasons), json.dumps(scored.matched_terms), json.dumps({k: v for k, v in scored.breakdown.__dict__.items() if k != "institute_score" or v}), scored.scored_at.isoformat()))
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
    def applications(self) -> list[Application]:
        return [_application(row) for row in self._rows("applications", "SELECT * FROM applications ORDER BY id")]
    def application(self, app_id: int) -> Application | None:
        rows = self._rows("applications", "SELECT * FROM applications WHERE id = ?", (app_id,))
        return _application(rows[0]) if rows else None
    def add_application(self, *, opportunity_number: str, grant_type: str, title: str, resubmission: bool = False) -> Application:
        key = (opportunity_number, grant_type, int(resubmission))
        with self._write("applications"):
            self.conn.execute("INSERT INTO applications (opportunity_number, grant_type, resubmission, title, created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(opportunity_number, grant_type, resubmission) DO NOTHING", (*key, title, _now()))
        return _application(self.conn.execute("SELECT * FROM applications WHERE opportunity_number = ? AND grant_type = ? AND resubmission = ?", key).fetchone())
    def set_disclosure(self, app_id: int, on: bool) -> None:
        with self._write("applications"):
            self.conn.execute("UPDATE applications SET disclosure_on = ? WHERE id = ?", (int(on), app_id))
    def delete_application(self, app_id: int) -> None:
        # The delete triggers let a row go only while this setting names its application.
        with self._write("applications"):
            self.conn.execute("INSERT INTO settings VALUES ('deleting', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(app_id),))
            self.conn.execute("DELETE FROM settings WHERE key IN (SELECT 'discarded:' || id FROM model_calls WHERE application_id = ?)", (app_id,))
            for table in ("signoffs", "reviews", "revisions", "requirements", "facts", "model_calls"):
                self.conn.execute(f"DELETE FROM {table} WHERE application_id = ?", (app_id,))
            self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
            self.conn.execute("DELETE FROM settings WHERE key = 'deleting'")
    def announcement(self, number: str) -> Announcement | None:
        rows = self._rows("announcements", "SELECT * FROM announcements WHERE opportunity_number = ?", (number,))
        return Announcement(rows[0]["opportunity_number"], rows[0]["text"], rows[0]["origin"], rows[0]["url"], rows[0]["sha256"], datetime.fromisoformat(rows[0]["fetched_at"])) if rows else None
    def save_announcement(self, a: Announcement) -> None:
        with self._write("announcements"):
            self.conn.execute("INSERT INTO announcements VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(opportunity_number) DO UPDATE SET text=excluded.text, origin=excluded.origin, url=excluded.url, sha256=excluded.sha256, fetched_at=excluded.fetched_at", (a.opportunity_number, a.text, a.origin, a.url, a.sha256, a.fetched_at.isoformat()))
    def facts(self, app_id: int) -> list[Fact]:
        return [Fact(row["id"], row["kind"], row["text"], row["label"], json.loads(row["detail_json"]), _time(row["retired_at"])) for row in self._rows("facts", "SELECT * FROM facts WHERE application_id = ? ORDER BY id", (app_id,))]
    def add_fact(self, app_id: int, kind: str, text: str, label: str = "", detail: dict[str, Any] | None = None) -> Fact:
        with self._write("facts"):
            fact_id = self.conn.execute("INSERT INTO facts (application_id, kind, label, text, detail_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (app_id, kind, label, text, json.dumps(detail or {}), _now())).lastrowid
        return next(f for f in self.facts(app_id) if f.id == fact_id)
    def retire_fact(self, fact_id: int) -> None:
        with self._write("facts"):
            self.conn.execute("UPDATE facts SET retired_at = ? WHERE id = ? AND retired_at IS NULL", (_now(), fact_id))
    def requirements(self, app_id: int) -> list[Requirement]:
        return [Requirement(row["kind"], row["text"], row["quote"], row["origin"], row["section"], Limit(**json.loads(row["limit_json"])) if row["limit_json"] else None, None if row["confirmed"] is None else bool(row["confirmed"]), row["id"], row["call_id"]) for row in self._rows("requirements", "SELECT * FROM requirements WHERE application_id = ? ORDER BY id", (app_id,))]
    def replace_requirements(self, app_id: int, origin: str, items: Iterable[Requirement], call_id: int | None = None) -> list[Requirement]:
        with self._write("requirements"):
            self.conn.execute("DELETE FROM requirements WHERE application_id = ? AND origin = ?", (app_id, origin))
            self.conn.executemany("INSERT INTO requirements (application_id, section, kind, text, quote, limit_json, origin, call_id, confirmed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", [(app_id, r.section, r.kind, r.text, r.quote, json.dumps(asdict(r.limit)) if r.limit else None, origin, r.call_id if r.call_id is not None else call_id, None if r.confirmed is None else int(r.confirmed)) for r in items])
        return [r for r in self.requirements(app_id) if r.origin == origin]
    def decide_requirement(self, requirement_id: int, confirmed: bool) -> None:
        with self._write("requirements"):
            self.conn.execute("UPDATE requirements SET confirmed = ? WHERE id = ?", (int(confirmed), requirement_id))
    def calls(self, app_id: int) -> list[ModelCall]:
        return [ModelCall(row["id"], row["section"], row["purpose"], row["provider"], row["model"], row["system"], row["prompt"], row["response"], row["input_tokens"], row["output_tokens"], datetime.fromisoformat(row["created_at"]), row["parent_id"]) for row in self._rows("model_calls", "SELECT * FROM model_calls WHERE application_id = ? ORDER BY id", (app_id,))]
    def add_call(self, app_id: int, section: str, purpose: str, provider: str, model: str, system: str, prompt: str, response: str, input_tokens: int = 0, output_tokens: int = 0, *, parent_id: int | None = None) -> ModelCall:
        with self._write("model_calls"):
            if parent_id is not None:
                self._own_revision(parent_id, app_id, section)
            call_id = self.conn.execute("INSERT INTO model_calls (application_id, section, purpose, provider, model, system, prompt, response, input_tokens, output_tokens, created_at, parent_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (app_id, section, purpose, provider, model, system, prompt, response, input_tokens, output_tokens, _now(), parent_id)).lastrowid
        return next(c for c in self.calls(app_id) if c.id == call_id)
    def _own_revision(self, revision_id: int, app_id: int, section: str) -> None:
        if self.conn.execute("SELECT 1 FROM revisions WHERE id = ? AND application_id = ? AND section = ?", (revision_id, app_id, section)).fetchone() is None:
            raise ValueError(f"Revision {revision_id} is not a revision of application {app_id} in the section {section}.")
    def revisions(self, app_id: int) -> list[Revision]:
        return [Revision(row["id"], row["section"], row["parent_id"], row["author"], row["action"], row["text"], row["call_id"], datetime.fromisoformat(row["created_at"])) for row in self._rows("revisions", "SELECT * FROM revisions WHERE application_id = ? ORDER BY id", (app_id,))]
    def add_revision(self, app_id: int, section: str, parent_id: int | None, author: str, action: str, text: str, call_id: int | None = None, only_on_head: bool = False, then: str | None = None, head: int | None = None) -> Revision | None:
        # With only_on_head, the insert itself checks that the parent, or head when given, is still the newest revision, so a save from another tab in between writes nothing and this returns None.
        # With then, the applicant's text goes on top of this revision in the same transaction, and the newer of the two is returned.
        at = _now()
        with self._write("revisions"):
            if parent_id is not None:
                self._own_revision(parent_id, app_id, section)
            # A call that does not exist is left to the foreign key.
            if call_id is not None and (call := self.conn.execute("SELECT application_id, section FROM model_calls WHERE id = ?", (call_id,)).fetchone()) is not None and tuple(call) != (app_id, section):
                raise ValueError(f"Call {call_id} is not a call of application {app_id} in the section {section}.")
            guard = " WHERE (SELECT MAX(id) FROM revisions WHERE application_id = ? AND section = ?) IS ?" if only_on_head else ""
            cursor = self.conn.execute("INSERT INTO revisions (application_id, section, parent_id, author, action, text, call_id, created_at) SELECT ?, ?, ?, ?, ?, ?, ?, ?" + guard, (app_id, section, parent_id, author, action, text, call_id, at, *((app_id, section, parent_id if head is None else head) if only_on_head else ())))
            if cursor.rowcount and then is not None:
                cursor = self.conn.execute("INSERT INTO revisions (application_id, section, parent_id, author, action, text, created_at) VALUES (?, ?, ?, 'applicant', 'write', ?, ?)", (app_id, section, cursor.lastrowid, then, at))
        return next(r for r in self.revisions(app_id) if r.id == cursor.lastrowid) if cursor.rowcount else None
    def signoffs(self, app_id: int) -> list[Signoff]:
        return [Signoff(row["section"], row["revision_id"], row["signer"], row["attestation"], tuple(json.loads(row["findings_json"])), row["tool_version"], datetime.fromisoformat(row["signed_at"])) for row in self._rows("signoffs", "SELECT * FROM signoffs WHERE application_id = ? ORDER BY id", (app_id,))]
    def add_signoff(self, app_id: int, section: str, revision_id: int, signer: str, attestation: str, findings: Sequence[str], tool_version: str) -> Signoff:
        signed_at = _now()
        with self._write("signoffs"):
            self._own_revision(revision_id, app_id, section)
            self.conn.execute("INSERT INTO signoffs (application_id, section, revision_id, signer, attestation, findings_json, tool_version, signed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (app_id, section, revision_id, signer, attestation, json.dumps(list(findings)), tool_version, signed_at))
        return Signoff(section, revision_id, signer, attestation, tuple(findings), tool_version, datetime.fromisoformat(signed_at))
    def reviews(self, app_id: int) -> list[Review]:
        return [Review(row["revision_id"], (data := json.loads(row["review_json"]))["scores"], tuple(ReviewPoint(**p) for p in data["points"]), data["model"], data["dropped"]) for row in self._rows("reviews", "SELECT * FROM reviews WHERE application_id = ? ORDER BY id", (app_id,))]
    def add_review(self, app_id: int, revision_id: int, call_id: int, review: Review) -> None:
        with self._write("reviews"):
            if self.conn.execute("SELECT 1 FROM model_calls WHERE id = ? AND application_id = ? AND purpose = 'review' AND parent_id = ?", (call_id, app_id, revision_id)).fetchone() is None:
                raise ValueError(f"Call {call_id} is not a review of revision {revision_id} of application {app_id}.")
            self.conn.execute("INSERT INTO reviews (application_id, revision_id, call_id, review_json, created_at) VALUES (?, ?, ?, ?, ?)", (app_id, revision_id, call_id, json.dumps({k: v for k, v in asdict(review).items() if k != "revision_id"}), _now()))
    def setting(self, key: str) -> str | None:
        rows = self._rows("settings", "SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None
    def set_setting(self, key: str, value: str) -> None:
        if key == "deleting":
            raise ValueError("The setting deleting belongs to delete_application.")
        with self._write("settings"):
            self.conn.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def _application(row: sqlite3.Row) -> Application:
    return Application(row["id"], row["opportunity_number"], row["grant_type"], row["title"], bool(row["resubmission"]), bool(row["disclosure_on"]), datetime.fromisoformat(row["created_at"]))
