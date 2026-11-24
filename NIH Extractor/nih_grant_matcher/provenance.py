from __future__ import annotations
from difflib import SequenceMatcher
from typing import Collection, Literal, Mapping, Sequence
from . import __version__
from .models import Application, Attribution, Fact, ModelCall, Revision, Signoff
from .rules import GrantType

PROPOSALS = ("polish", "revise", "draft")
_KINDS = {"aim": "aims", "hypothesis": "hypotheses", "preliminary": "preliminary data", "method": "methods", "significance": "significance", "innovation": "innovation", "team": "team", "reference": "references", "other": "other inputs"}

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

def _listed(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"

def disclosure_statement(application: Application, grant_type: GrantType, revisions: Sequence[Revision], calls: Sequence[ModelCall], signoffs: Sequence[Signoff], facts: Sequence[Fact], waiting: Collection[int], shares: Mapping[str, Attribution] | None = None) -> str:
    # Each sentence stands only on what the log holds, so the statement cannot claim more than the record shows. waiting names the proposals that can still be accepted, and shares, when given, are the head attributions the caller already computed.
    said, closing = [f"AI use in this application, from the record that Grant Matcher {__version__} keeps."], "This record covers work done in Grant Matcher. It does not cover text that I wrote or edited elsewhere."
    if not calls:
        return " ".join([*said, "No AI model was used on this application in Grant Matcher.", closing])
    rules = [r for r in grant_type.sections if application.resubmission or not r.resubmission_only]
    titles = lambda keys: _listed([r.title for r in rules if r.key in keys])
    heads = {r.key: h for r in rules if (h := head(revisions, r.key)) is not None}
    if kinds := {f.kind for f in facts if f.retired_at is None}:
        said.append(f"I entered the {_listed([name for kind, name in _KINDS.items() if kind in kinds])} of this application myself.")
    accepted, used = {r.call_id for r in revisions if r.call_id is not None}, {}
    for c in calls:
        if c.id in accepted:
            used.setdefault((c.model, c.provider, c.purpose), set()).add(c.section)
    said += [f"I used {model} ({provider}) to {action} the {titles(sections)}." for (model, provider, action), sections in used.items()]
    first_model = {}
    for r in sorted(revisions, key=lambda r: r.id):
        if r.author == "model":
            first_model.setdefault(r.section, r.id)
    if edited := {r.section for r in revisions if r.author == "applicant" and r.id > first_model.get(r.section, r.id)}:
        said.append(f"I edited {titles(edited)} after I accepted model text.")
    shares = {key: shares[key] if shares is not None else share(attribution(revisions, h.id)) for key, h in heads.items()}
    said += [f"By the tool's word-level record, {round(s.written_share * 100)} percent of the {r.title} text came from a model's draft or revision that I accepted, and {round(s.polished_share * 100)} percent from a model's polish of my own text." for r in rules if (s := shares.get(r.key)) and s.model_words]
    if without := [key for key, h in heads.items() if h.text.strip() and not shares[key].model_words]:
        said.append(f"The {titles(without)} {'was' if len(without) == 1 else 'were'} written without a model.")
    unused = [c for c in calls if c.purpose == "failed" or (c.purpose in PROPOSALS and c.id not in accepted and c.id not in waiting)]
    for model in dict.fromkeys(c.model for c in calls if c.purpose in ("extract", "review") or c in unused):
        parts = [part for purpose, part in (("extract", "read the funding announcement's requirements"), ("review", "review drafts against NIH's review criteria")) if any(c.model == model and c.purpose == purpose for c in calls)]
        if n := sum(c.model == model for c in unused):
            parts.append(f"produce suggestions that I did not use ({n})")
        said.append(f"I also sent text to {model} to {_listed(parts)}.")
    if signed := [key for key, h in heads.items() if any(s.section == key and s.revision_id == h.id for s in signoffs)]:
        said.append(f"I read and signed off {titles(signed)}.")
    return " ".join([*said, closing])
