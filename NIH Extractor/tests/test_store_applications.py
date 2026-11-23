import sqlite3, pytest
from nih_grant_matcher.store import OpportunityStore

@pytest.fixture
def store(tmp_path):
    store = OpportunityStore(tmp_path / "g.sqlite3")
    yield store
    store.close()

def _app(store) -> int:
    return store.add_application(opportunity_number="PAR-1", grant_type="NIH:R21", title="t", resubmission=False).id

def test_a_model_revision_needs_a_logged_call(store) -> None:
    app = _app(store)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_revision(app, "specific-aims", None, "model", "draft", "text", call_id=None)
    with pytest.raises(sqlite3.IntegrityError):
        store.add_revision(app, "specific-aims", None, "applicant", "draft", "text", call_id=None)

def test_revisions_cannot_be_changed_or_removed(store) -> None:
    revision = store.add_revision(_app(store), "specific-aims", None, "applicant", "write", "mine", call_id=None)
    for statement in ("UPDATE revisions SET text = 'x' WHERE id = ?", "DELETE FROM revisions WHERE id = ?"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store.conn.execute(statement, (revision.id,))

def test_a_model_revision_cannot_name_a_call_that_does_not_exist(store) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        store.add_revision(_app(store), "specific-aims", None, "model", "polish", "text", call_id=999)

def test_one_application_per_opportunity_type_and_resubmission(store) -> None:
    first = _app(store)
    assert first == store.add_application(opportunity_number="PAR-1", grant_type="NIH:R21", title="t", resubmission=False).id
    assert first != store.add_application(opportunity_number="PAR-1", grant_type="NIH:R01", title="t", resubmission=False).id
    assert first != store.add_application(opportunity_number="PAR-1", grant_type="NIH:R21", title="t", resubmission=True).id

def test_deleting_an_application_removes_its_log_and_nothing_else(store) -> None:
    keep, gone = _app(store), store.add_application(opportunity_number="PAR-2", grant_type="NIH:R21", title="t", resubmission=False).id
    store.add_revision(keep, "specific-aims", None, "applicant", "write", "keep", call_id=None)
    store.add_revision(gone, "specific-aims", None, "applicant", "write", "gone", call_id=None)
    store.delete_application(gone)
    assert [a.id for a in store.applications()] == [keep] and store.revisions(gone) == [] and len(store.revisions(keep)) == 1
    assert store.setting("deleting") is None

def test_the_schema_can_run_twice(tmp_path) -> None:
    OpportunityStore(tmp_path / "g.sqlite3").close()
    OpportunityStore(tmp_path / "g.sqlite3").close()

def test_an_existing_database_gains_the_tables(tmp_path) -> None:
    path = tmp_path / "old.sqlite3"
    sqlite3.connect(path).executescript("CREATE TABLE opportunities (source_id TEXT PRIMARY KEY, title TEXT NOT NULL);")
    store = OpportunityStore(path)
    try:
        assert store.applications() == []
    finally:
        store.close()

def test_every_record_reads_back_as_it_was_written(store) -> None:
    from datetime import datetime
    from nih_grant_matcher.announcement import Announcement, Requirement
    from nih_grant_matcher.rules import Limit
    app = _app(store)
    announcement = Announcement("PAR-1", "text", "nih-guide", "https://example.org", "abc", datetime(2026, 11, 23, 9, 30))
    store.save_announcement(announcement)
    assert store.announcement("PAR-1") == announcement and store.announcement("PAR-2") is None
    fact = store.add_fact(app, "aim", "Aim one.", label="Aim 1", detail={"order": 1})
    store.retire_fact(fact.id)
    [retired] = store.facts(app)
    assert (retired.kind, retired.text, retired.label, retired.detail) == ("aim", "Aim one.", "Aim 1", {"order": 1}) and retired.retired_at is not None
    call = store.add_call(app, "specific-aims", "draft", "anthropic", "claude-opus-5-5", "sys", "prompt", "reply", 10, 20)
    assert store.calls(app) == [call]
    store.replace_requirements(app, "parsed", (Requirement("limit", "Specific Aims: at most 1 pages.", "q", "parsed", "specific-aims", Limit(1.0, "pages")),))
    [found] = store.replace_requirements(app, "model", (Requirement("must", "Name a mentor.", "q", "model", call_id=call.id),), call_id=call.id)
    store.decide_requirement(found.id, True)
    parsed, model = store.requirements(app)
    assert (parsed.limit, parsed.origin, parsed.confirmed) == (Limit(1.0, "pages"), "parsed", None) and (model.call_id, model.confirmed) == (call.id, True)
    revision = store.add_revision(app, "specific-aims", None, "model", "draft", "text", call_id=call.id)
    assert store.revisions(app) == [revision]
    signoff = store.add_signoff(app, "specific-aims", revision.id, "A. Applicant", "I wrote this.", ("page-limit",), "0.3.0")
    assert store.signoffs(app) == [signoff] and signoff.findings == ("page-limit",)
    store.set_disclosure(app, False)
    assert store.application(app).disclosure_on is False and store.application(999) is None
    store.set_setting("provider", "anthropic")
    assert store.setting("provider") == "anthropic"

def test_a_read_only_database_from_an_earlier_version_reads_as_empty(tmp_path) -> None:
    import os
    from nih_grant_matcher.store import ReadOnlyDatabase
    path = tmp_path / "old.sqlite3"
    sqlite3.connect(path).executescript("CREATE TABLE opportunities (source_id TEXT PRIMARY KEY, title TEXT NOT NULL); CREATE TABLE scores (source_id TEXT PRIMARY KEY);")
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    try:
        store = OpportunityStore(path)
        try:
            assert store.applications() == store.facts(1) == store.requirements(1) == store.calls(1) == store.revisions(1) == store.signoffs(1) == []
            assert store.application(1) is None and store.announcement("PAR-1") is None and store.setting("deleting") is None
            with pytest.raises(ReadOnlyDatabase, match="read-only"):
                store.add_application(opportunity_number="PAR-1", grant_type="NIH:R21", title="t", resubmission=False)
        finally:
            store.close()
    finally:
        path.chmod(0o644)
