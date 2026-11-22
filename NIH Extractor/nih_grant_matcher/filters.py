from __future__ import annotations
import re
from datetime import date
from .models import Opportunity

ACTIVE_STATUSES = {"posted", "forecasted", "active", "activenosis", "notices"}
NIH_TOKENS = ("nih", "national institutes of health", "hhs", "niddk", "ninds", "rmod", "roadmap", "common fund", "nhlbi", "nci", "nia", "nimh", "nibib", "nhgri", "ncats")

def is_current_nih_hhs_opportunity(opportunity: Opportunity, today: date | None = None) -> bool:
    today = today or date.today()
    status = (opportunity.status or "").lower()
    agency = f"{opportunity.agency_code} {opportunity.agency_name}".lower()
    is_nih_guide = str(opportunity.source_id).startswith("nih-guide:")
    if status and status not in ACTIVE_STATUSES:
        return False
    # Single-word tokens match whole words, so "nia" does not match "Virginia".
    words = set(re.findall(r"[a-z]+", agency))
    if not is_nih_guide and not any(token in agency if " " in token else token in words for token in NIH_TOKENS):
        return False
    if opportunity.close_date and opportunity.close_date < today:
        return False
    return True
