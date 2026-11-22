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


def test_reporter_context_prints_projects(monkeypatch, capsys) -> None:
    monkeypatch.setattr(NihReporterClient, "search_projects", lambda self, term, limit=25: [{"project_num": "R01", "term": term, "limit": limit}])
    assert cli.main(["reporter-context", "--term", "imaging", "--limit", "3"]) == 0
    assert '"term": "imaging"' in capsys.readouterr().out


def test_backfill_xml_reports_a_certificate_error(monkeypatch, tmp_path, capsys) -> None:
    def fail(self, destination):
        raise urllib.error.URLError(ssl.SSLCertVerificationError("unable to get local issuer certificate"))
    monkeypatch.setattr(GrantsGovXmlClient, "download_latest", fail)
    assert cli.main(["backfill-xml", "--out", str(tmp_path / "x.zip")]) == 1
    assert "Could not verify the certificate" in capsys.readouterr().err


def test_xml_extract_url_is_resolved_against_the_page(monkeypatch) -> None:
    from nih_grant_matcher import clients
    monkeypatch.setattr(clients, "_get_bytes", lambda url, timeout=60: b'<a href="/extract/GrantsDBExtract20261122v2.zip">zip</a>')
    assert GrantsGovXmlClient().latest_extract_url() == "https://www.grants.gov/extract/GrantsDBExtract20261122v2.zip"
