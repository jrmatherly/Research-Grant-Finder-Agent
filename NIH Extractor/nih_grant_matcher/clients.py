from __future__ import annotations
import http.client, json, ssl, time, urllib.error, urllib.parse, urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from .config import CROSSREF_WORKS_URL, GRANTSGOV_ATTACHMENT_URL, GRANTSGOV_FETCH_URL, GRANTSGOV_SEARCH_URL, NIH_GUIDE_API_URL, NIH_GUIDE_DOCTEXT_URL, NIH_REPORTER_SEARCH_URL, PUBMED_SUMMARY_URL

class ApiError(RuntimeError):
    pass

UNTITLED = "(the record has no title)"

def _certificate_failed(exc: BaseException) -> bool:
    # urllib wraps a failure on connect in URLError and leaves a later one bare.
    return isinstance(exc, ssl.SSLCertVerificationError) or isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError)

def _read(request: urllib.request.Request, timeout: int, attempts: int = 3) -> bytes:
    # A run makes hundreds of requests in a row, so one dropped connection or 5xx must not end it.
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            failure, final = exc, exc.code < 500 and exc.code != 429
        # urllib wraps only a failed send in URLError. A connection that drops while the response is read raises OSError or HTTPException.
        except (OSError, http.client.HTTPException) as exc:
            # A certificate that fails once fails every time, so do not retry it.
            failure, final = exc, _certificate_failed(exc)
        if final or attempt == attempts:
            hint = ". Python does not trust the server's certificate. Behind a proxy that inspects TLS, set SSL_CERT_FILE to the proxy's CA bundle." if _certificate_failed(failure) else ""
            # Name the address: the dashboard shows only this message, and a run can talk to two services.
            raise ApiError(f"{_address(request)} failed after {attempt} attempt(s): {failure}{hint}") from failure
        time.sleep(2 ** (attempt - 1))
    raise AssertionError("unreachable")

def _address(request: urllib.request.Request) -> str:
    # The NIH Guide query string is over 300 characters, and it would push the reason off the line.
    return request.full_url.split("?")[0]

def _read_json(request: urllib.request.Request, timeout: int) -> dict[str, Any]:
    body = _read(request, timeout)
    try:
        parsed = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        # A proxy or a block page answers 200 with HTML.
        raise ApiError(f"{_address(request)} did not return JSON. The reply starts with {body[:80]!r}") from exc
    if not isinstance(parsed, dict):
        raise ApiError(f"{_address(request)} returned JSON that is not an object")
    return parsed

def _number(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{name} is not a number: {value!r}") from None

def _post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", "User-Agent": "nih-grant-matcher/0.1"}, method="POST")
    parsed = _read_json(request, timeout)
    if parsed.get("errorcode") not in (None, 0):
        raise ApiError(f"{url} returned errorcode={parsed.get('errorcode')}: {parsed.get('msg')}")
    return parsed

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
        data = _post_json(self.fetch_url, {"opportunityId": _number(opportunity_id, "Grants.gov opportunity id")}).get("data")
        time.sleep(self.pause_seconds)
        if not isinstance(data, dict):
            raise ApiError(f"Unexpected Grants.gov fetch response for {opportunity_id}")
        return data
    def full_announcement(self, opportunity_id: str) -> str:
        folders = self.fetch_opportunity(opportunity_id).get("synopsisAttachmentFolders") or []
        if not isinstance(folders, list) or any(isinstance(f, dict) and not isinstance(f.get("synopsisAttachments") or [], list) for f in folders):
            raise ApiError(f"Unexpected Grants.gov fetch response for {opportunity_id}: an attachment list is not a list")
        found = [a for f in folders if isinstance(f, dict) for a in f.get("synopsisAttachments") or [] if isinstance(a, dict) and str(a.get("fileName", "")).endswith("Full-Announcement.html")]
        if not found:
            return ""
        def created(a: dict) -> datetime:
            try:
                return datetime.strptime(str(a.get("createdDate")).rpartition(" ")[0], "%b %d, %Y %I:%M:%S %p")
            except ValueError:
                return datetime.min
        # A revised announcement is a second attachment, and the list need not be in date order. A tie takes the later in the list.
        latest = max(enumerate(found), key=lambda pair: (created(pair[1]), pair[0]))[1]
        # The id goes into the URL path, so only a number may reach it.
        return _read(urllib.request.Request(f"{GRANTSGOV_ATTACHMENT_URL}/{_number(latest.get('id'), f'Grants.gov full announcement attachment id for {opportunity_id}')}", headers={"User-Agent": "nih-grant-matcher/0.1"}), 60).decode("utf-8", errors="replace")

@dataclass
class NihGuideClient:
    api_url: str = NIH_GUIDE_API_URL
    pause_seconds: float = 0.1
    def search(self, rows: int = 250, keyword: str = "", types: str = "active,activenosis") -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        page_size = min(100, max(1, rows))
        offset = 0
        while len(collected) < rows:
            request = _guide_request(f"{self.api_url}/data", perpage=page_size, sort="reldate:desc" if not keyword else "_score", offset=offset, types=types, keyword=keyword)
            parsed = _read_json(request, 30)
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
    def doctext(self, docnum: str) -> tuple[str, str]:
        parsed = _read_json(_guide_request(NIH_GUIDE_DOCTEXT_URL, perpage=5, sort="_score", offset=0, types="active,activenosis", keyword=docnum), 30)
        hits = (((parsed.get("data") or {}).get("hits") or {}).get("hits") or [])
        if not isinstance(hits, list):
            raise ApiError("Unexpected NIH Guide response: hits is not a list")
        sources = [hit.get("_source", hit) if isinstance(hit, dict) else None for hit in hits]
        # The search ranks by relevance, so the top hit can be another document that cites this number.
        source = next((source for source in sources if isinstance(source, dict) and source.get("docnum") == docnum), None)
        if source is None and not all(isinstance(source, dict) for source in sources):
            raise ApiError(f"Unexpected NIH Guide response for {docnum}: the hit is not an object")
        if source is None:
            return "", ""
        return str(source.get("doctext") or ""), str(source.get("ggid") or "")

def _guide_request(url: str, perpage: int, sort: str, offset: int, types: str, keyword: str) -> urllib.request.Request:
    params = {
        "perpage": perpage,
        "sort": sort,
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
    return urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "Origin": "https://grants.nih.gov", "Referer": "https://grants.nih.gov/funding/nih-guide-for-grants-and-contracts", "User-Agent": "nih-grant-matcher/0.1"},
    )

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

@dataclass
class ReferenceClient:
    pubmed_url: str = PUBMED_SUMMARY_URL
    crossref_url: str = CROSSREF_WORKS_URL
    # NCBI allows three requests a second without a key, and the lookups share one pace across both services.
    pause_seconds: float = 0.4
    # _read tries three times, so a dead network costs about half a minute per reference rather than a minute and a half.
    timeout: int = 10
    def lookup(self, pmid: str = "", doi: str = "") -> str:
        if not (pmid or doi):
            raise ValueError("A lookup needs a PMID or a DOI.")
        time.sleep(self.pause_seconds)
        try:
            title = self._pubmed(pmid) if pmid else self._crossref(doi)
        except ApiError as exc:
            raise ApiError(f"Checking {f'PMID {pmid} with PubMed' if pmid else f'DOI {doi} with Crossref'} failed: {exc}") from exc
        # The title is text from the network, printed in a terminal too, so a control character goes and it is cut to a line.
        return "" if title is None else " ".join("".join(c if c.isprintable() else " " for c in title).split())[:300] or UNTITLED
    def _pubmed(self, pmid: str) -> str | None:
        query = urllib.parse.urlencode({"db": "pubmed", "id": pmid, "retmode": "json", "tool": "nih-grant-matcher"})
        parsed = _read_json(urllib.request.Request(f"{self.pubmed_url}?{query}", headers={"User-Agent": "nih-grant-matcher/0.1"}), self.timeout)
        # NCBI answers an id it does not hold with 200 and an error, and a rate limit with an error too, so only the id's own errors mean no record.
        if "error" in parsed:
            if str(parsed["error"]).startswith("Invalid uid"):
                return None
            raise ApiError(f"PubMed answered with an error: {parsed['error']}")
        record = (parsed.get("result") or {}).get(pmid) if isinstance(parsed.get("result"), dict) else None
        if isinstance(record, dict) and "error" in record:
            return None
        if not isinstance(record, dict) or not isinstance(record.get("title"), str):
            raise ApiError("PubMed's reply holds no record or title for this PMID")
        return record["title"]
    def _crossref(self, doi: str) -> str | None:
        # The DOI goes into the URL path, so a ? or # in it cannot start a query or a fragment.
        request = urllib.request.Request(f"{self.crossref_url}/{urllib.parse.quote(doi, safe='/')}", headers={"User-Agent": "nih-grant-matcher/0.1"})
        try:
            parsed = _read_json(request, self.timeout)
        except ApiError as exc:
            # Crossref answers a DOI it does not hold with a 404, which _read keeps as the cause.
            if isinstance(exc.__cause__, urllib.error.HTTPError) and exc.__cause__.code == 404:
                return None
            raise
        title = parsed["message"].get("title") if isinstance(parsed.get("message"), dict) else None
        if not isinstance(title, list) or not all(isinstance(t, str) for t in title):
            raise ApiError("Crossref's reply holds no title list for this DOI")
        return " ".join(title)
