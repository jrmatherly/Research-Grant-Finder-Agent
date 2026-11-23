from __future__ import annotations
from difflib import SequenceMatcher
from typing import Literal, Sequence
from .models import Attribution, Revision, Signoff

def head(revisions: Sequence[Revision], section: str) -> Revision | None:
    return max((r for r in revisions if r.section == section), key=lambda r: r.id, default=None)

def attribution(revisions: Sequence[Revision], revision_id: int) -> tuple[tuple[str, str], ...]:
    by_id = {r.id: r for r in revisions}
    chain = [by_id[revision_id]]
    while chain[-1].parent_id is not None:
        if chain[-1].parent_id not in by_id:
            raise ValueError(f"Revision {chain[-1].id} names parent {chain[-1].parent_id}, which is not in the log given.")
        chain.append(by_id[chain[-1].parent_id])
    ordered = chain[::-1]
    # Every word of a run of applicant revisions is the applicant's, so the diffs start at the last one before a model's.
    first = next((i for i, r in enumerate(ordered) if r.author != "applicant"), len(ordered))
    words = [(w, "applicant") for w in ordered[first - 1].text.split()] if first else []
    for revision in ordered[first:]:
        new, origin = revision.text.split(), "applicant" if revision.author == "applicant" else revision.action
        opcodes = SequenceMatcher(a=[w for w, _ in words], b=new, autojunk=False).get_opcodes()
        words = [pair for tag, i1, i2, j1, j2 in opcodes for pair in (words[i1:i2] if tag == "equal" else [(w, origin) for w in new[j1:j2]])]
    return tuple(words)

def share(words: Sequence[tuple[str, str]]) -> Attribution:
    origins = [origin for _, origin in words]
    if unknown := set(origins) - {"applicant", "draft", "revise", "polish"}:
        raise ValueError(f"Unknown word origin: {', '.join(sorted(unknown))}")
    return Attribution(origins.count("applicant"), origins.count("draft") + origins.count("revise"), origins.count("polish"))

def section_state(revisions: Sequence[Revision], signoffs: Sequence[Signoff], section: str) -> Literal["empty", "draft", "final"]:
    current = head(revisions, section)
    if current is None:
        return "empty"
    return "final" if any(s.section == section and s.revision_id == current.id for s in signoffs) else "draft"
