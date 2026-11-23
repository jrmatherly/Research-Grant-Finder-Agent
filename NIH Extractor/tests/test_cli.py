import ssl
import urllib.error
from datetime import date, timedelta

import pytest

from nih_grant_matcher import cli, workflow
from nih_grant_matcher.clients import GrantsGovClient, GrantsGovXmlClient, NihGuideClient, NihReporterClient

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


def test_backfill_xml_reports_a_failed_download(monkeypatch, tmp_path, capsys) -> None:
    from nih_grant_matcher.clients import ApiError
    def fail(self, destination):
        raise ApiError("https://www.grants.gov/xml-extract failed after 3 attempt(s): HTTP Error 503")
    monkeypatch.setattr(GrantsGovXmlClient, "download_latest", fail)
    assert cli.main(["backfill-xml", "--out", str(tmp_path / "x.zip")]) == 1
    assert "HTTP Error 503" in capsys.readouterr().err


def test_reporter_context_prints_projects(monkeypatch, capsys) -> None:
    monkeypatch.setattr(NihReporterClient, "search_projects", lambda self, term, limit=25: [{"project_num": "R01", "term": term, "limit": limit}])
    assert cli.main(["reporter-context", "--term", "imaging", "--limit", "3"]) == 0
    assert '"term": "imaging"' in capsys.readouterr().out


def test_backfill_xml_reports_a_certificate_error(monkeypatch, tmp_path, capsys) -> None:
    def fail(self, destination):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
    monkeypatch.setattr(GrantsGovXmlClient, "download_latest", fail)
    assert cli.main(["backfill-xml", "--out", str(tmp_path / "x.zip")]) == 1
    assert "unable to get local issuer certificate" in capsys.readouterr().err


def test_xml_extract_url_is_resolved_against_the_page(monkeypatch) -> None:
    from nih_grant_matcher import clients
    monkeypatch.setattr(clients, "_get_bytes", lambda url, timeout=60: b'<a href="/extract/GrantsDBExtract20261122v2.zip">zip</a>')
    assert GrantsGovXmlClient().latest_extract_url() == "https://www.grants.gov/extract/GrantsDBExtract20261122v2.zip"


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
