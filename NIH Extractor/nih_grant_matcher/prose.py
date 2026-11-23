# The rules are adapted from the unslop skill in the jstack plugin, MIT licence, Copyright (c) 2026 Lauren Tan.
from __future__ import annotations
import re
from dataclasses import dataclass
from .models import Finding

@dataclass(frozen=True)
class ProseRule:
    number: int
    name: str
    hint: str
    pattern: re.Pattern[str] | None

def _words(*words: str, end: str = r"\b") -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + ")" + end, re.I)

# The month May is not a hedge.
_HEDGES = r"(?:(?-i:may)|might|could|possibly|potentially|perhaps|arguably|somewhat)"
# Rules 15 to 18 are left out because NIH headings are title case by rule and the editor is plain text.
PROSE_RULES: tuple[ProseRule, ...] = (
    ProseRule(3, "-ing opener", "A clause after a comma opens with a word like highlighting or ensuring and adds no fact. Cut it or state the fact.", re.compile(r", (?:highlighting|ensuring|reflecting|showcasing|fostering)\b", re.I)),
    ProseRule(5, "vague attribution", "A claim rests on unnamed experts or studies. Name the source or cut the claim.", None),
    ProseRule(7, "marked word", "This word marks text as written by a model. Use a plain word in its place.", _words("additionally", "crucial", "delve", "enduring", "enhance", "fostering", "garner", "interplay", "intricate", "landscape", "pivotal", "showcase", "tapestry", "testament", "underscore", "vibrant")),
    ProseRule(8, "grand verb", "A grand verb stands in for a plain is or has. Write is or has.", _words("serves as", "stands as", "boasts")),
    ProseRule(9, "denied claim", "The sentence denies a claim nobody made before it makes its own. State the claim directly.", re.compile(r"\bnot (?:just|only) .{1,60}, but\b", re.I)),
    ProseRule(10, "forced triple", "A list of three is there for rhythm and not for content. Keep only the items that carry a fact.", None),
    ProseRule(11, "synonym cycling", "One thing goes by several names in turn. Use one name throughout.", None),
    ProseRule(12, "false range", "A range from one thing to another joins things that sit on no common scale. Name the items plainly.", None),
    ProseRule(13, "em dash", "An em dash joins two thoughts. Use a period, a comma or parentheses.", re.compile("—")),
    # A heading at the start of a line, with an optional label, may take a colon. A time or a ratio has no space after its colon.
    ProseRule(14, "colon join", "A colon joins two clauses in mid-sentence. Make them two sentences.", re.compile(r"^(?![ \t]*(?:(?:[A-Za-z]|\d+)[.)][ \t]*)?(?:[A-Z][\w/'-]*[ \t]+)*[A-Z][\w/'-]*:)[^\n]*?(?P<hit>\b\w*[a-z]: +[a-z]\w*)", re.M)),
    ProseRule(19, "curly quotes", "Curly quotation marks come from a model or a word processor. Use straight quotes.", re.compile("[‘’“”]")),
    ProseRule(20, "chat phrase", "This phrase belongs in a chat reply and not in an application. Delete it.", re.compile(r"\b(?:I hope this helps|Let me know if|Of course!|Certainly!|Great question)", re.I)),
    ProseRule(23, "padded phrase", "A long phrase stands where one word would do. Write to or because, or cut the phrase.", _words("in order to", "due to the fact that", "it is important to note that")),
    ProseRule(24, "stacked hedges", "Two hedges close together make the claim vague. Keep one or none.", re.compile(rf"\b{_HEDGES}\b(?:\W+\w+){{0,4}}?\W+{_HEDGES}\b", re.I)),
    ProseRule(25, "generic conclusion", "The closing line restates the section in general terms. End on the last specific point.", None),
    ProseRule(26, "abstract metaphor", "A metaphor noun such as journey or roadmap stands in for a plan. Name the steps of the plan.", None),
    ProseRule(27, "feeling for mechanism", "The sentence says how a result feels in place of how it works. State the mechanism.", None),
    ProseRule(28, "dense sentence", "The sentence carries more ideas than a reader can hold at once. Split it.", None),
    ProseRule(29, "passive voice", "A passive verb hides who acts. Name the actor.", None),
    ProseRule(30, "adverb", "An adverb props up a weak verb or claim. Cut it or use a stronger verb.", None),
    # Rule 31 has no closing boundary, so utilized and leveraged match.
    ProseRule(31, "inflated word", "A long word stands where a short one would do. Write use, help, many or if.", _words("utilise", "utilize", "leverage", "facilitate", "numerous", "in the event that", end="")),
    ProseRule(32, "mannered prose", "The phrasing reaches for style over sense. Say it plainly.", None),
    ProseRule(33, "over-compression", "Words a reader needs to follow the sentence are missing. Write the full sentence.", None))

def scan(text: str) -> tuple[Finding, ...]:
    findings = []
    for rule in PROSE_RULES:
        if rule.pattern and (matches := list(rule.pattern.finditer(text))):
            first = matches[0].group("hit") if "hit" in rule.pattern.groupindex else matches[0].group()
            findings.append(Finding(f"prose-{rule.number}", "warning", rule.hint + (f" It comes up {len(matches)} times in this section." if len(matches) > 1 else ""), first))
    return tuple(findings)
