from __future__ import annotations
import json, re, ssl, time, urllib.error, urllib.parse, urllib.request, zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .config import GRANTSGOV_FETCH_URL, GRANTSGOV_SEARCH_URL, GRANTSGOV_XML_EXTRACT_URL, NIH_GUIDE_API_URL, NIH_REPORTER_SEARCH_URL

class ApiError(RuntimeError):
    pass

def _read(request: urllib.request.Request, timeout: int, attempts: int = 3) -> bytes:
    # A run makes hundreds of requests in a row, so one dropped connection or 5xx must not end it.
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts or isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
                raise
        time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")

def _post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "nih-grant-matcher/0.1"}, method="POST")
    parsed = json.loads(_read(request, timeout).decode("utf-8"))
    if isinstance(parsed, dict) and parsed.get("errorcode") not in (None, 0):
        raise ApiError(f"{url} returned errorcode={parsed.get('errorcode')}: {parsed.get('msg')}")
    return parsed

def _get_bytes(url: str, timeout: int = 60) -> bytes:
    return _read(urllib.request.Request(url, headers={"User-Agent": "nih-grant-matcher/0.1"}), timeout)

@dataclass
class GrantsGovClient:
    search_url: str = GRANTSGOV_SEARCH_URL
    fetch_url: str = GRANTSGOV_FETCH_URL
    pause_seconds: float = 0.25
    def search(self, agencies: list[str], statuses: list[str], rows: int = 50, keyword: str = "", start_record: int = 0) -> list[dict[str, Any]]:
        payload = {"rows": rows, "startRecordNum": start_record, "keyword": keyword, "agencies": "|".join(agencies), "oppStatuses": "|".join(statuses), "resultType": "json"}
        hits = (_post_json(self.search_url, payload).get("data") or {}).get("oppHits") or []
        if not isinstance(hits, list):
            raise ApiError("Unexpected Grants.gov search response: oppHits is not a list")
        return hits
    def search_all(self, agencies: list[str], statuses: list[str], limit: int = 250, keyword: str = "") -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page_size = min(100, max(1, limit))
        start_record = 0
        while len(collected) < limit:
            hits = self.search(agencies, statuses, rows=page_size, keyword=keyword, start_record=start_record)
            if not hits:
                break
            collected.extend(hits)
            if len(hits) < page_size:
                break
            start_record += len(hits)
        return collected[:limit]
    def fetch_opportunity(self, opportunity_id: str | int) -> dict[str, Any]:
        data = _post_json(self.fetch_url, {"opportunityId": int(opportunity_id)}).get("data")
        time.sleep(self.pause_seconds)
        if not isinstance(data, dict):
            raise ApiError(f"Unexpected Grants.gov fetch response for {opportunity_id}")
        return data

@dataclass
class GrantsGovXmlClient:
    extract_page_url: str = GRANTSGOV_XML_EXTRACT_URL
    def latest_extract_url(self) -> str:
        html = _get_bytes(self.extract_page_url).decode("utf-8", errors="replace")
        matches = re.findall(r'href="([^"]*GrantsDBExtract\d+v\d+\.zip[^"]*)"', html) or re.findall(r"(https://[^\s\"']*GrantsDBExtract\d+v\d+\.zip)", html)
        if not matches:
            raise ApiError("No GrantsDBExtract zip link found on Grants.gov XML extract page")
        latest = matches[-1]
        return latest if latest.startswith("http") else urllib.request.urljoin(self.extract_page_url, latest)
    def download_latest(self, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(_get_bytes(self.latest_extract_url()))
        if not zipfile.is_zipfile(destination):
            raise ApiError(f"Downloaded file is not a zip archive: {destination}")
        return destination

@dataclass
class NihGuideClient:
    api_url: str = NIH_GUIDE_API_URL
    pause_seconds: float = 0.1
    def search(self, rows: int = 250, keyword: str = "", types: str = "active,activenosis") -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page_size = min(100, max(1, rows))
        offset = 0
        while len(collected) < rows:
            params = {
                "perpage": page_size,
                "sort": "reldate:desc" if not keyword else "_score",
                "from": offset,
                "type": types,
                "parentic": "all",
                "primaryic": "all",
                "activitycodes": "all",
                "doctype": "all",
                "parentfoa": "all",
                "daterange": "01011991-12312030",
                "clinicaltrials": "all",
                "fields": "all",
                "spons": "true",
                "query": keyword,
                "apptype": "all",
                "noticeSubject": "all",
                "category": "all",
            }
            query = urllib.parse.urlencode(params)
            request = urllib.request.Request(
                f"{self.api_url}/data?{query}",
                headers={"Accept": "application/json", "Origin": "https://grants.nih.gov", "Referer": "https://grants.nih.gov/funding/nih-guide-for-grants-and-contracts", "User-Agent": "nih-grant-matcher/0.1"},
            )
            parsed = json.loads(_read(request, 30).decode("utf-8"))
            hits = (((parsed.get("data") or {}).get("hits") or {}).get("hits") or [])
            if not isinstance(hits, list):
                raise ApiError("Unexpected NIH Guide response: hits is not a list")
            if not hits:
                break
            collected.extend(hit.get("_source", hit) for hit in hits)
            if len(hits) < page_size:
                break
            offset += len(hits)
            time.sleep(self.pause_seconds)
        return collected[:rows]

@dataclass
class NihReporterClient:
    search_url: str = NIH_REPORTER_SEARCH_URL
    pause_seconds: float = 1.0
    def search_projects(self, term: str, limit: int = 25) -> list[dict[str, Any]]:
        payload = {"criteria": {"advanced_text_search": {"operator": "or", "search_field": "projecttitle,terms,abstracttext", "search_text": term}, "include_active_projects": True}, "include_fields": ["ApplId", "ProjectNum", "ProjectTitle", "AbstractText", "AgencyIcAdmin", "FiscalYear", "OpportunityNumber", "AwardAmount"], "limit": limit, "offset": 0, "sort_field": "award_notice_date", "sort_order": "desc"}
        results = _post_json(self.search_url, payload).get("results") or []
        time.sleep(self.pause_seconds)
        if not isinstance(results, list):
            raise ApiError("Unexpected NIH RePORTER response: results is not a list")
        return results
