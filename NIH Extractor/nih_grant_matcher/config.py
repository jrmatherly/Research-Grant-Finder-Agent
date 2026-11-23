from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

GRANTSGOV_SEARCH_URL = "https://api.grants.gov/v1/api/search2"
GRANTSGOV_FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"
NIH_REPORTER_SEARCH_URL = "https://api.reporter.nih.gov/v2/projects/search"
NIH_GUIDE_API_URL = "https://vtbgfslh0k.execute-api.us-east-1.amazonaws.com/prod"
NIH_GUIDE_DOCTEXT_URL = "https://search.grants.nih.gov/guide/api/data"
GRANTSGOV_ATTACHMENT_URL = "https://apply07.grants.gov/grantsws/rest/opportunity/att/download"

DEFAULT_KEYWORDS = {
    "machine learning": 18, "artificial intelligence": 18, "deep learning": 18,
    "predictive model": 16, "predictive modeling": 16, "prediction model": 16,
    "clinical prediction": 16, "risk model": 14, "natural language processing": 16,
    "computer vision": 16, "clinical decision support": 12, "multimodal data": 12, "data science": 14, "statistical modeling": 12,
    "bioinformatics": 12, "computational": 10, "omics": 10, "ehr": 10,
    "electronic health record": 10, "imaging analytics": 12, "data analysis": 8,
    "analytics": 7, "algorithm": 7, "modeling": 6,
    # Data infrastructure and quantitative methods. Half of the relevant opportunities in a labeled sample named none of the terms above.
    "medical imaging": 12, "data integration": 10, "informatics": 12, "biostatistics": 12, "statistical": 8, "quantitative": 8,
    "data coordination": 10, "data management": 8, "data standards": 10, "data harmonization": 10, "secondary analysis": 10, "data resource": 8, "data sharing": 6,
}
# A keyword listed here is matched with its own pattern. "omics" covers genomics and proteomics, but not economics.
KEYWORD_PATTERNS = {
    "omics": r"\b(?!\w*(?:econ|ergon)omics)\w*omics\b",
    "biostatistics": r"\bbiostatistic\w*", "data coordination": r"\bdata coordinat\w*", "data standards": r"\bdata standard\w*",
    "data harmonization": r"\bdata harmoni[sz]\w*", "secondary analysis": r"\bsecondary (?:data )?analys\w*",
    # Not "statistically significant", and not the "Data Management and Sharing Plan" that every application carries.
    "statistical": r"\bstatistic(?:al|s|ians?)\b", "data management": r"\bdata management(?! and sharing)",
    # "AI/AN" is American Indian and Alaska Native, not artificial intelligence.
    "ai": r"\bai\b(?!\s*/\s*ans?\b)",
}
# Built by `python -m nih_grant_matcher rarity-table` from expired NIH Guide opportunities.
TERM_RARITY_PATH = Path(__file__).with_name("term_rarity.json")
CURATED_COMPUTATIONAL_EXAMPLES = (
    "Develop machine learning models to predict clinical risk from electronic health records.",
    "Use deep learning and computer vision to analyze biomedical imaging data.",
    "Apply bioinformatics and multi-omics data integration to identify disease mechanisms.",
    "Create predictive models and statistical learning tools for patient outcomes.",
    "Use natural language processing to extract phenotypes from clinical text.",
    "Build artificial intelligence methods for biomedical data analysis.",
)
GENERIC_BIOMEDICAL_TERMS = {"clinical trial", "health disparities", "community health", "training program", "capacity building", "implementation", "prevention", "therapeutic"}

@dataclass(frozen=True)
class MatcherConfig:
    agencies: tuple[str, ...] = ("HHS-NIH11",)
    statuses: tuple[str, ...] = ("posted", "forecasted")
    rows: int = 500
    min_digest_score: float = 0.0
    db_path: str = "data/grants.sqlite3"
    keywords: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_KEYWORDS))
    semantic_examples: tuple[str, ...] = CURATED_COMPUTATIONAL_EXAMPLES
    focus: str = "computational"
    examples_name: str = "curated ML/data-science grant examples"
