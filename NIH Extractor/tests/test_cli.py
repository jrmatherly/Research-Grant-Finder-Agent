from datetime import date, timedelta

import pytest

from nih_grant_matcher import cli, workflow
from nih_grant_matcher.clients import GrantsGovClient, NihGuideClient, NihReporterClient

CLOSE = date.today() + timedelta(days=60)
GUIDE_ITEM = {"rowid": "1", "type": "active", "title": "Machine learning for imaging", "docnum": "RFA-XX-27-001", "primaryIC": "NIBIB", "expdate": f"{CLOSE.isoformat()}T00:00:00.000Z", "doctype": "RFA", "purpose": "Deep learning for biomedical imaging data."}
CLOSED_ITEM = {"rowid": "2", "type": "active", "title": "Closed notice", "docnum": "RFA-XX-20-009", "primaryIC": "NIBIB", "expdate": "2020-01-01T00:00:00.000Z"}


def _hit(opportunity_id: int, number: str) -> dict:
    return {"id": opportunity_id, "number": number, "title": "Bioinformatics tools", "agencyCode": "HHS-NIH11", "agencyName": "National Institutes of Health", "closeDate": CLOSE.strftime("%m/%d/%Y"), "oppStatus": "posted"}


@pytest.fixture
def sources(monkeypatch):
    # Both sources return the same opportunity number once, so the run must keep the NIH Guide record.
    monkeypatch.setattr(NihGuideClient, "search", lambda self, rows=250, keyword="", types="": [GUIDE_ITEM, CLOSED_ITEM])
    monkeypatch.setattr(GrantsGovClient, "search_all", lambda self, agencies, statuses, limit=250, keyword="": [_hit(11, "RFA-XX-27-001"), _hit(12, "PAR-XX-27-002")])
    monkeypatch.setattr(GrantsGovClient, "fetch_opportunity", lambda self, opportunity_id: {"id": opportunity_id})


def test_run_saves_current_deduped_opportunities_and_writes_the_digest(sources, tmp_path, capsys) -> None:
    db, out = tmp_path / "g.sqlite3", tmp_path / "digests" / "latest.md"
    assert cli.main(["--db", str(db), "run", "--source", "both", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Fetched 4 opportunities from both." in printed
    assert "Saved 2 current NIH/HHS opportunities" in printed
    digest = out.read_text(encoding="utf-8")
    assert "Included opportunities: 2" in digest
    assert "Machine learning for imaging" in digest and "Bioinformatics tools" in digest
    assert "Closed notice" not in digest
    assert "- Matched terms: machine learning, deep learning" in digest
    assert [item.opportunity.source_id for item in workflow.load_saved(str(db))] == ["nih-guide:1", "12"]


def test_digest_and_excel_commands_read_saved_results(sources, tmp_path, capsys) -> None:
    db = tmp_path / "g.sqlite3"
    cli.main(["--db", str(db), "run", "--out", str(tmp_path / "first.md")])
    assert cli.main(["--db", str(db), "digest", "--out", str(tmp_path / "again.md"), "--min-score", "99.5"]) == 0
    assert "No opportunities met the current threshold." in (tmp_path / "again.md").read_text(encoding="utf-8")
    assert cli.main(["--db", str(db), "excel", "--out", str(tmp_path / "out.xlsx")]) == 0
    assert (tmp_path / "out.xlsx").stat().st_size > 0
    assert "Wrote Excel file" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["run", "digest", "excel"])
def test_each_command_scores_saved_rows_again(sources, tmp_path, command: str) -> None:
    from dataclasses import replace
    from nih_grant_matcher.models import Opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    from nih_grant_matcher.store import OpportunityStore
    # A saved row that the sources do not return, with no deadline, holding a score that no rule gives it.
    fresh = MLRelevanceScorer().score(Opportunity(source_id="nih-guide:77", opportunity_number="RFA-STALE", title="Machine learning for health", agency_code="NIH", agency_name="National Institutes of Health", status="active"))
    db = tmp_path / "g.sqlite3"
    store = OpportunityStore(db)
    try:
        store.upsert_scored(replace(fresh, score=1.0))
    finally:
        store.close()
    assert cli.main(["--db", str(db), command, "--out", str(tmp_path / ("out.xlsx" if command == "excel" else "out.md"))]) == 0
    store = OpportunityStore(db)
    try:
        assert {item.opportunity.source_id: item.score for item in store.top_scored(limit=-1)}["nih-guide:77"] == fresh.score != 1.0
    finally:
        store.close()


def test_run_and_save_reports_fetched_and_saved_counts(sources, tmp_path) -> None:
    items, summary = workflow.run_and_save(workflow.MatcherConfig(db_path=str(tmp_path / "g.sqlite3")), source="grants.gov")
    assert (summary.fetched, summary.saved, summary.source) == (2, 2, "grants.gov")
    assert [item.score for item in items] == sorted((item.score for item in items), reverse=True)


def test_workflow_dedupe_keeps_the_guide_record_for_a_shared_number() -> None:
    from nih_grant_matcher.models import Opportunity
    def opp(source_id: str, number: str) -> Opportunity:
        return Opportunity(source_id=source_id, opportunity_number=number, title="t", agency_code="", agency_name="", status="posted")
    kept = workflow._dedupe_opportunities([opp("nih-guide:1", "RFA-1"), opp("11", "RFA-1"), opp("12", ""), opp("13", "")])
    assert [item.source_id for item in kept] == ["nih-guide:1", "12", "13"]


def test_rarity_table_keeps_the_old_table_when_the_fetch_is_short(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(NihGuideClient, "search", lambda self, rows=250, keyword="", types="": [])
    out = tmp_path / "table.json"
    out.write_text("old", encoding="utf-8")
    assert cli.main(["rarity-table", "--out", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "old"
    assert "was not replaced" in capsys.readouterr().err


def test_reporter_context_prints_projects(monkeypatch, capsys) -> None:
    monkeypatch.setattr(NihReporterClient, "search_projects", lambda self, term, limit=25: [{"project_num": "R01", "term": term, "limit": limit}])
    assert cli.main(["reporter-context", "--term", "imaging", "--limit", "3"]) == 0
    assert '"term": "imaging"' in capsys.readouterr().out


def test_rarity_table_counts_documents_per_term_and_drops_singletons(monkeypatch, tmp_path, capsys) -> None:
    import json
    items = [{"rowid": "1", "docnum": "PA-1", "title": "Imaging imaging", "purpose": "Imaging research."}, {"rowid": "2", "docnum": "PA-2", "title": "Research", "purpose": "Once only."}]
    monkeypatch.setattr(NihGuideClient, "search", lambda self, rows=250, keyword="", types="": items if types == "expired" else [])
    out = tmp_path / "table.json"
    assert cli.main(["rarity-table", "--rows", "2", "--out", str(out)]) == 0
    table = json.loads(out.read_text(encoding="utf-8"))
    assert table["documents"] == 2
    assert table["terms"]["research"] == 2
    assert "imaging" not in table["terms"] and "once" not in table["terms"]


def test_run_says_when_it_reaches_the_limit(sources, tmp_path, capsys) -> None:
    db = tmp_path / "g.sqlite3"
    assert cli.main(["--db", str(db), "run", "--limit", "2", "--out", str(tmp_path / "d.md")]) == 0
    assert "A source returned 2 rows" in capsys.readouterr().err
    assert cli.main(["--db", str(db), "run", "--source", "grants.gov", "--limit", "2", "--out", str(tmp_path / "d.md")]) == 0
    assert "A source returned 2 rows" in capsys.readouterr().err
    # Each source returns 2 rows. Together they pass a limit of 3, but neither source reaches it.
    assert cli.main(["--db", str(db), "run", "--source", "both", "--limit", "3", "--out", str(tmp_path / "d.md")]) == 0
    assert capsys.readouterr().err == ""
    assert cli.main(["--db", str(db), "run", "--out", str(tmp_path / "d.md")]) == 0
    assert capsys.readouterr().err == ""
    assert cli.build_parser().parse_args(["run"]).limit == 500


def test_digest_calls_the_date_an_expiration(sources, tmp_path) -> None:
    out = tmp_path / "d.md"
    cli.main(["--db", str(tmp_path / "g.sqlite3"), "run", "--out", str(out)])
    digest = out.read_text(encoding="utf-8")
    assert f"- Expires: {CLOSE.isoformat()}" in digest
    assert f"  - Open until {CLOSE.isoformat()}" in digest
    assert "eadline" not in digest

def test_digest_replaces_a_saved_deadline_reason(tmp_path) -> None:
    from dataclasses import replace
    from nih_grant_matcher.models import Opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    from nih_grant_matcher.store import OpportunityStore
    saved = MLRelevanceScorer().score(Opportunity(source_id="nih-guide:5", opportunity_number="RFA-OLD", title="Machine learning for health", agency_code="NIH", agency_name="National Institutes of Health", status="active", close_date=CLOSE))
    db, out = tmp_path / "g.sqlite3", tmp_path / "d.md"
    store = OpportunityStore(db)
    try:
        store.upsert_scored(replace(saved, reasons=(f"Deadline is still active: {CLOSE.isoformat()}",)))
    finally:
        store.close()
    assert cli.main(["--db", str(db), "digest", "--out", str(out)]) == 0
    assert "eadline" not in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("argv, target", [(["run"], (NihGuideClient, "search")), (["reporter-context", "--term", "x"], (NihReporterClient, "search_projects"))])
def test_a_failed_request_exits_1_with_one_line(monkeypatch, tmp_path, capsys, argv, target) -> None:
    from nih_grant_matcher.clients import ApiError
    def fail(self, *args, **kwargs):
        raise ApiError("https://example.invalid/data failed after 3 attempt(s): HTTP Error 503")
    monkeypatch.setattr(*target, fail)
    assert cli.main(["--db", str(tmp_path / "g.sqlite3"), *argv]) == 1
    assert capsys.readouterr().err == "Request failed: https://example.invalid/data failed after 3 attempt(s): HTTP Error 503\n"
    assert not (tmp_path / "g.sqlite3").exists()


def test_digest_escapes_markup_in_a_title_and_a_summary() -> None:
    from nih_grant_matcher.digest import render_digest
    from nih_grant_matcher.models import Opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    # A Markdown viewer reads "<" as the start of an HTML tag, and then hides or runs what follows.
    scored = MLRelevanceScorer().score(Opportunity(source_id="nih-guide:9", opportunity_number="PAR<9", title="Models with p<0.05 and n>30", agency_code="NIH", agency_name="National Institutes of Health", status="active", description="<img src=x onerror=alert(1)> & more"))
    digest = render_digest([scored], min_score=0)
    assert "## 1. Models with p&lt;0.05 and n>30" in digest
    assert "&lt;img src=x onerror=alert(1)> & more" in digest
    assert "- Opportunity number: PAR&lt;9" in digest
    assert "<" not in digest


def test_run_and_save_reports_a_capped_source(sources, tmp_path) -> None:
    from nih_grant_matcher.config import MatcherConfig
    assert workflow.run_and_save(MatcherConfig(rows=2, db_path=str(tmp_path / "a.sqlite3")))[1].capped is True
    assert workflow.run_and_save(MatcherConfig(rows=3, db_path=str(tmp_path / "b.sqlite3")))[1].capped is False


def test_run_and_save_ranks_with_the_saved_profile(sources, tmp_path) -> None:
    from nih_grant_matcher.config import MatcherConfig
    from nih_grant_matcher.profile import Profile
    from nih_grant_matcher.store import OpportunityStore
    db = str(tmp_path / "g.sqlite3")
    store = OpportunityStore(db)
    try:
        store.save_profile(Profile(keywords={"biomedical imaging": 12}, examples=("Deep learning for biomedical imaging data.",), focus="profile", examples_name="your example sentences"))
    finally:
        store.close()
    items, _ = workflow.run_and_save(MatcherConfig(db_path=db))
    assert any(reason.startswith("Matched profile terms") for item in items for reason in item.reasons)


def test_profile_import_show_export_and_reset(tmp_path, capsys) -> None:
    import json
    from nih_grant_matcher.profile import BUILTIN_PROFILE, Profile, to_export
    from nih_grant_matcher.store import OpportunityStore
    db, path = str(tmp_path / "g.sqlite3"), tmp_path / "p.json"
    profile = Profile(investigator="Ada Lovelace", keywords={"mitochondria": 18}, examples=("Study mitochondria.",), focus="profile", examples_name="your example sentences")
    path.write_text(to_export(profile), encoding="utf-8")
    assert cli.main(["--db", db, "profile", "import", str(path)]) == 0
    store = OpportunityStore(db)
    try:
        assert store.profile() == profile
    finally:
        store.close()
    capsys.readouterr()
    assert cli.main(["--db", db, "profile", "show"]) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(to_export(profile))["profile"]
    assert cli.main(["--db", db, "profile", "export", "--out", str(tmp_path / "out.json")]) == 0
    assert (tmp_path / "out.json").read_text(encoding="utf-8") == to_export(profile) + "\n"
    assert cli.main(["--db", db, "profile", "reset"]) == 0
    store = OpportunityStore(db)
    try:
        assert store.profile() == BUILTIN_PROFILE
    finally:
        store.close()
    path.write_text('{"format": "other/9"}', encoding="utf-8")
    assert cli.main(["--db", db, "profile", "import", str(path)]) == 1
    assert "format" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["profile", "import", "missing.json"], ["profile", "import", "latin1.json"], ["profile", "export", "--out", "nodir/x.json"]])
def test_a_file_that_cannot_be_read_or_written_exits_1_with_one_line(tmp_path, monkeypatch, capsys, argv) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "latin1.json").write_bytes(b"\xff\xfe caf\xe9")
    assert cli.main(["--db", "g.sqlite3", *argv]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "Traceback" not in err


def test_a_database_error_gets_one_line(tmp_path, capsys) -> None:
    (tmp_path / "g.sqlite3").write_bytes(b"not a database" * 100)
    assert cli.main(["--db", str(tmp_path / "g.sqlite3"), "profile", "show"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Database error:") and err.count("\n") == 1 and "Traceback" not in err


def test_a_read_only_database_from_before_says_what_to_do(tmp_path, capsys) -> None:
    import os, sqlite3
    path = tmp_path / "old.sqlite3"
    sqlite3.connect(path).executescript("CREATE TABLE opportunities (source_id TEXT PRIMARY KEY, title TEXT NOT NULL);")
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    try:
        assert cli.main(["--db", str(path), "profile", "reset"]) == 1
    finally:
        path.chmod(0o644)
    err = capsys.readouterr().err
    assert "not valid" not in err and "read-only" in err and "copy" in err and err.count("\n") == 1


def _apply_db(tmp_path) -> str:
    from helpers import opportunity
    from nih_grant_matcher.scoring import MLRelevanceScorer
    from nih_grant_matcher.store import OpportunityStore
    store = OpportunityStore(tmp_path / "g.sqlite3")
    try:
        store.upsert_scored(MLRelevanceScorer().score(opportunity()))
    finally:
        store.close()
    return str(tmp_path / "g.sqlite3")


def test_apply_starts_writes_checks_signs_and_exports(tmp_path, capsys) -> None:
    db, text = _apply_db(tmp_path), tmp_path / "narrative.txt"
    assert cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"]) == 0
    assert cli.main(["--db", db, "apply", "list"]) == 0
    assert "PAR-1" in capsys.readouterr().out
    text.write_text("One. Two. Three. Four.", encoding="utf-8")
    assert cli.main(["--db", db, "apply", "write", "1", "project-narrative", "--file", str(text)]) == 0
    assert cli.main(["--db", db, "apply", "check", "1"]) == 1
    assert "over-limit" in capsys.readouterr().out
    assert cli.main(["--db", db, "apply", "sign", "1", "project-narrative", "--signer", "A. Applicant"]) == 1
    assert "over-limit" in capsys.readouterr().err
    text.write_text("One. Two. Three.", encoding="utf-8")
    assert cli.main(["--db", db, "apply", "write", "1", "project-narrative", "--file", str(text)]) == 0
    assert cli.main(["--db", db, "apply", "check", "1"]) == 0
    assert cli.main(["--db", db, "apply", "sign", "1", "project-narrative", "--signer", "A. Applicant"]) == 0
    assert "I have read this section." in capsys.readouterr().out
    assert cli.main(["--db", db, "apply", "export", "1", "--out", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "project-narrative.md").read_text(encoding="utf-8").endswith("One. Two. Three.\n")
    assert (tmp_path / "out" / "DRAFT-specific-aims.md").exists()


def test_apply_adds_a_fact_and_lists_the_requirements(tmp_path, capsys) -> None:
    db = _apply_db(tmp_path)
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    assert cli.main(["--db", db, "apply", "add", "1", "--kind", "aim", "--text", "Map heart cells."]) == 0
    assert cli.main(["--db", db, "apply", "requirements", "1"]) == 0
    assert "Research Strategy" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["start", "PAR-1", "--type", "R01"], ["start", "PAR-9", "--type", "R21"], ["check", "7"], ["write", "1", "budget", "--file", "x.txt"], ["add", "1", "--kind", "budget", "--text", "x"], ["write", "1", "specific-aims", "--file", "missing.txt"], ["delete", "1"]])
def test_an_apply_mistake_is_one_line_and_exit_1(tmp_path, monkeypatch, capsys, argv) -> None:
    db = _apply_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    capsys.readouterr()
    assert cli.main(["--db", db, "apply", *argv]) == 1
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "Traceback" not in err
    assert cli.main(["--db", db, "apply", "list"]) == 0 and "PAR-1" in capsys.readouterr().out


def test_apply_delete_with_yes_deletes(tmp_path, capsys) -> None:
    db = _apply_db(tmp_path)
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    assert cli.main(["--db", db, "apply", "delete", "1", "--yes"]) == 0
    capsys.readouterr()
    cli.main(["--db", db, "apply", "list"])
    assert "PAR-1" not in capsys.readouterr().out


@pytest.mark.parametrize("text, said", [("A notice with no headings at all. " * 40, True), ("Section IV. Application and Submission Information\nThe Research Strategy is limited to 4 pages.\nSection V. Review\nx", False)])
def test_apply_fetch_and_requirements_say_when_the_text_has_no_section_iv(tmp_path, monkeypatch, capsys, text, said) -> None:
    from nih_grant_matcher.clients import NihGuideClient
    monkeypatch.setattr(NihGuideClient, "doctext", lambda self, number: (text, "1"))
    db = _apply_db(tmp_path)
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    for action in ("fetch", "requirements"):
        capsys.readouterr()
        assert cli.main(["--db", db, "apply", action, "1"]) == 0
        assert ("found no Section IV" in capsys.readouterr().out) == said


def test_apply_check_prints_a_signed_section_with_a_new_error_as_a_draft(tmp_path, capsys) -> None:
    from nih_grant_matcher.store import OpportunityStore
    db, text = _apply_db(tmp_path), tmp_path / "aims.txt"
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    cli.main(["--db", db, "apply", "add", "1", "--kind", "reference", "--text", "Smith J. Heart cells. 2021.", "--label", "smith2021"])
    text.write_text("As we showed [@smith2021].", encoding="utf-8")
    cli.main(["--db", db, "apply", "write", "1", "specific-aims", "--file", str(text)])
    assert cli.main(["--db", db, "apply", "sign", "1", "specific-aims", "--signer", "A. Applicant"]) == 0
    capsys.readouterr()
    assert cli.main(["--db", db, "apply", "check", "1"]) == 0 and "specific-aims  final" in capsys.readouterr().out
    store = OpportunityStore(db)
    try:
        store.retire_fact(store.facts(1)[0].id)
    finally:
        store.close()
    assert cli.main(["--db", db, "apply", "check", "1"]) == 1
    out = capsys.readouterr().out
    assert "specific-aims  draft" in out and "draft again" in out


def test_apply_export_prints_the_absolute_folder(tmp_path, monkeypatch, capsys) -> None:
    db = _apply_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    cli.main(["--db", db, "apply", "start", "PAR-1", "--type", "R21"])
    capsys.readouterr()
    assert cli.main(["--db", db, "apply", "export", "1", "--out", "out"]) == 0
    assert f"Wrote the application to {(tmp_path / 'out').resolve()}." in capsys.readouterr().out
