"""Grade a seller's text reply: how hot is this lead?

Two graders share one output shape:
  * RuleGrader  - keyword/phrase rules, free, instant, no setup.
  * ClaudeGrader - asks Claude to read the reply in context; used when
    ANTHROPIC_API_KEY is set, falls back to the rules on any error.

Score is 0-100. Tiers: HOT >= 75, WARM 50-74, COLD 25-49, DEAD < 25,
and DNC for opt-outs (never text them again).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

TIERS = ("HOT", "WARM", "COLD", "DEAD", "DNC")


@dataclass
class Grade:
    score: int
    tier: str
    reasons: list[str] = field(default_factory=list)
    grader: str = "rules"


def tier_for(score: int) -> str:
    if score >= 75:
        return "HOT"
    if score >= 50:
        return "WARM"
    if score >= 25:
        return "COLD"
    return "DEAD"


# (pattern, points, reason). Checked against the lowercased reply.
OPT_OUT = [
    r"^\s*(stop|stopall|unsubscribe|end|quit|cancel)\s*[.!]*\s*$",
    r"\b(remove me|take me off|stop texting|stop messaging|do not (text|contact)|don'?t (text|contact))\b",
    r"\b(wrong number|wrong person|don'?t own|do not own|never owned|sold (it|the house) already)\b",
]
NEGATIVE = [
    (r"\bnot (interested|selling|for sale)\b|\bno (thanks|thank you)\b|\bnot looking to sell\b|\bwon'?t sell\b|\bnever sell(ing)?\b", -45, "declined"),
    (r"^\s*no\s*[.!]*\s*$|^\s*nope\s*[.!]*\s*$", -40, "flat no"),
    (r"\b(scam|lowball|vulture|harass|reported|lawyer|attorney general)\b", -35, "hostile"),
    (r"\b(f+u+c*k+|shit|piss off|go away|leave me alone)\b", -45, "hostile"),
]
HOT = [
    (r"\b(yes|yeah|yep|sure|absolutely|definitely)\b", 20, "affirmative"),
    (r"\binterested\b", 25, "says interested"),
    (r"\b(learn|hear|know|tell me) more\b|\bmore info(rmation)?\b|\bmore details\b", 40, "wants more info"),
    (r"\b(want|looking|ready|willing|thinking( about)?|considering|need|trying) (to )?sell(ing)?\b", 35, "wants to sell"),
    (r"\bi'?d sell\b|\bwould sell\b|\bopen to (selling|offers?)\b", 30, "open to selling"),
    (r"\b(what|how much) (would|will|can|could) you (offer|pay|give)\b|\bmake (me )?an offer\b|\bsend (me )?(an|your) offer\b|\bwhat'?s (your|the) offer\b|\bcash offer\b", 35, "asking for an offer"),
    (r"\bhow much\b|\bprice\b|\bwhat'?s it worth\b|\bvalue\b", 15, "asking about price"),
    (r"\bcall me\b|\bgive me a call\b|\bcan (you|we) (talk|call|meet)\b|\bwhen can you\b|\bcome (see|look|by)\b|\bset up a time\b", 30, "wants a call/visit"),
    (r"\b(asap|quickly|fast|soon|urgent|this (week|month))\b", 10, "urgency"),
    (r"\b(divorce|probate|inherited|behind on (payments|mortgage)|foreclosure|relocat|moving|tired landlord|bad tenants?|vacant|repairs?|fixer)\b", 15, "motivation signal"),
]
WARM = [
    (r"\b(maybe|possibly|might|depends|not sure|perhaps)\b", 10, "maybe"),
    (r"\bwho is this\b|\bwho are you\b|\bhow did you get\b|\bwhat company\b", 5, "curious who we are"),
    (r"\bnot (right )?now\b|\bin a (few|couple) (months|years)\b|\bnext year\b|\blater\b|\bfuture\b", 5, "timing is later"),
    (r"\?", 5, "asked a question"),
]


class RuleGrader:
    name = "rules"

    def grade(self, text: str, history: list[str] | None = None) -> Grade:
        t = text.lower().strip()
        if any(re.search(p, t) for p in OPT_OUT):
            return Grade(0, "DNC", ["opt-out / wrong number"], self.name)
        score, reasons = 35, []
        negated = False
        for pat, pts, why in NEGATIVE:
            if re.search(pat, t):
                score += pts
                reasons.append(why)
                negated = True
        for pat, pts, why in HOT:
            if re.search(pat, t):
                # "not interested" already counted as a decline; don't also reward "interested".
                if negated and why in ("says interested", "affirmative", "wants to sell"):
                    continue
                score += pts
                reasons.append(why)
        for pat, pts, why in WARM:
            if re.search(pat, t):
                score += pts
                reasons.append(why)
        score = max(0, min(100, score))
        return Grade(score, tier_for(score), reasons or ["no clear signal"], self.name)


PROMPT = """You grade replies from homeowners to a real estate investor's text \
asking if they'd consider selling their house. Grade how likely this person \
is to become a seller lead.

HOT (75-100): wants to sell, asks for an offer or price, wants more info, asks for a call.
WARM (50-74): open but unsure, "maybe", "depends on price", selling later.
COLD (25-49): mild no, vague, or only curious who is texting.
DEAD (0-24): firm no or hostile.
DNC: asks to stop, wrong number, or doesn't own the property. Score 0.

Earlier messages in this conversation (oldest first), may be empty:
{history}

Latest reply to grade:
{text}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "tier": {"type": "string", "enum": list(TIERS)},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "tier", "reasons"],
    "additionalProperties": False,
}


class ClaudeGrader:
    """LLM grader. Falls back to RuleGrader on any API error or refusal."""
    name = "claude"

    def __init__(self, model: str = "claude-opus-5"):
        import anthropic  # imported lazily so the rules work without the SDK
        self.client = anthropic.Anthropic()
        self.model = model
        self.fallback = RuleGrader()

    def grade(self, text: str, history: list[str] | None = None) -> Grade:
        rules = self.fallback.grade(text)
        if rules.tier == "DNC":
            return rules  # opt-outs are decided by rules, never overridden
        try:
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=1024,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": PROMPT.format(
                    history="\n".join(history or []) or "(none)", text=text)}],
            )
            if resp.stop_reason == "refusal":
                return rules
            data = json.loads(next(b.text for b in resp.content if b.type == "text"))
            score = max(0, min(100, int(data["score"])))
            tier = data["tier"] if data["tier"] == "DNC" else tier_for(score)
            return Grade(score, tier, data["reasons"][:4], self.name)
        except Exception as exc:  # network, auth, parse: keep the pipeline running
            rules.reasons.append(f"claude unavailable: {type(exc).__name__}")
            return rules


def default_grader():
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return ClaudeGrader(os.environ.get("SIFTER_MODEL", "claude-opus-5"))
        except ImportError:
            pass
    return RuleGrader()
