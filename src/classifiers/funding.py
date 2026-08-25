"""Funding extraction from public announcements (spec 13 'capital').

An organization that has just raised is materially easier to engage: it has a
budget, a mandate to spend it, and usually a public commitment about what the
money is for. That makes funding a genuine outreach signal.

It is also the signal most easily corrupted by inference, so this module is
deliberately conservative:

* A round is recorded only from an explicit published figure. Nothing is
  estimated, and an undisclosed round stays undisclosed.
* The verbatim sentence is stored alongside the parsed number so an analyst can
  check the parse rather than trust it.
* Investment is never read as acquisition interest. Spec 13 requires an
  explicitly stated formal process for `investment_ma`, and "raised a Series A"
  is not that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.config import settings
from src.util.timeutil import parse_iso, utcnow

# Multipliers for written magnitudes.
_MAGNITUDES = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "mm": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000,
}

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

# "$12M", "$12.5 million", "USD 5,000,000", "€3m"
_AMOUNT = re.compile(
    r"(?P<symbol>[$€£¥])?\s*(?P<code>USD|EUR|GBP|JPY)?\s*"
    r"(?P<number>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(?P<magnitude>k|m|mm|bn|b|thousand|million|billion)?\b",
    re.IGNORECASE,
)

# Round labels, longest-first so "pre-seed" wins over "seed".
_ROUND_PATTERNS: List[tuple[str, re.Pattern]] = [
    ("pre_seed", re.compile(r"\bpre[-\s]?seed\b", re.I)),
    ("series_a", re.compile(r"\bseries\s+a\b", re.I)),
    ("series_b", re.compile(r"\bseries\s+b\b", re.I)),
    ("series_c", re.compile(r"\bseries\s+c\b", re.I)),
    ("strategic", re.compile(r"\bstrategic (?:investment|round|financing)\b", re.I)),
    ("ecosystem_fund", re.compile(r"\becosystem fund\b", re.I)),
    ("grant", re.compile(r"\b(?:grant|grant programme|grant program)\b", re.I)),
    ("token_sale", re.compile(r"\b(?:token sale|public sale|ido|ico)\b", re.I)),
    ("seed", re.compile(r"\bseed (?:round|funding|financing)\b|\bseed\b", re.I)),
]

# Only sentences making a raise claim are parsed for amounts, so an unrelated
# "$50 fee" elsewhere on the page cannot become a funding round.
_RAISE_VERBS = re.compile(
    r"\b(rais(?:ed|es|ing)|secur(?:ed|es)|clos(?:ed|es)\s+(?:a|its)|"
    r"announc(?:ed|es)\s+(?:a|its)?\s*(?:\$|new\s+)?(?:funding|round|investment)|"
    r"led\s+by|backed\s+by|funding\s+round|investment\s+round)\b",
    re.I,
)

_LEAD = re.compile(r"\bled\s+by\s+(?P<lead>[A-Z][\w&.\-' ]{2,60}?)(?:\s*(?:,|\.|and|with|$))", re.M)
_PARTICIPATION = re.compile(
    r"\b(?:with participation from|joined by|participation from|alongside)\s+"
    r"(?P<investors>[^.]{3,240})",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class FundingSignal:
    """One extracted, evidence-backed funding claim."""

    round_type: str
    amount_usd: Optional[float]
    amount_as_published: Optional[str]
    currency: str
    investors: List[str] = field(default_factory=list)
    lead_investor: Optional[str] = None
    quote: str = ""
    confidence: float = 0.0
    announced_at: Optional[datetime] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "round_type": self.round_type,
            "amount_usd": self.amount_usd,
            "amount_as_published": self.amount_as_published,
            "currency": self.currency,
            "investors": self.investors,
            "lead_investor": self.lead_investor,
            "quote": self.quote,
            "confidence": self.confidence,
            "announced_at": self.announced_at.isoformat() if self.announced_at else None,
        }


def parse_amount(text: str) -> tuple[Optional[float], Optional[str], str]:
    """Parse the first monetary amount in a sentence.

    Returns ``(amount_usd, as_published, currency)``. Non-USD amounts are kept
    as published with no conversion: an FX rate applied silently would turn a
    reported figure into an engine-invented one.
    """
    for match in _AMOUNT.finditer(text):
        number_raw = match.group("number")
        symbol = match.group("symbol")
        code = (match.group("code") or "").upper()
        magnitude = (match.group("magnitude") or "").lower()

        currency = _CURRENCY_SYMBOLS.get(symbol or "", "") or code
        if not currency:
            # A bare number with no currency marker is not a funding figure.
            continue

        try:
            value = float(number_raw.replace(",", ""))
        except ValueError:
            continue
        if magnitude:
            value *= _MAGNITUDES.get(magnitude, 1)
        elif value < 1000:
            # "$12" without a magnitude is not a round; avoid inventing millions.
            continue

        as_published = match.group(0).strip()
        if currency not in settings.FUNDING.supported_currencies:
            return None, as_published, currency
        return value, as_published, currency
    return None, None, "USD"


def _split_investors(blob: str) -> List[str]:
    parts = re.split(r",| and (?![\w&.\-' ]*\bCapital\b)", blob)
    investors: List[str] = []
    for part in parts:
        name = part.strip(" .;:-—").strip()
        # Trim trailing clause noise while keeping multi-word fund names.
        name = re.sub(r"\s+(among others|and others|etc\.?)$", "", name, flags=re.I)
        if 2 < len(name) <= 60 and not name.lower().startswith(("the round", "this round")):
            investors.append(name)
    return investors[:12]


class FundingExtractor:
    """Extracts funding rounds from official announcements and news."""

    def extract(
        self,
        text: str,
        *,
        is_official_source: bool = False,
        published_at: Optional[datetime] = None,
    ) -> List[FundingSignal]:
        if not text:
            return []

        signals: List[FundingSignal] = []
        for sentence in _SENTENCE.split(text):
            sentence = sentence.strip()
            if not sentence or not _RAISE_VERBS.search(sentence):
                continue

            amount_usd, as_published, currency = parse_amount(sentence)
            round_type = next(
                (name for name, pattern in _ROUND_PATTERNS if pattern.search(sentence)),
                "undisclosed",
            )
            if amount_usd is None and as_published is None and round_type == "undisclosed":
                # Neither a figure nor a named round: nothing worth recording.
                continue

            lead_match = _LEAD.search(sentence)
            lead = lead_match.group("lead").strip() if lead_match else None
            investors = list(_split_investors(lead)) if lead else []
            participation = _PARTICIPATION.search(sentence)
            if participation:
                investors.extend(_split_investors(participation.group("investors")))

            # Confidence reflects how much was actually stated, and whether the
            # project said it or somebody else reported it.
            confidence = 0.30
            if amount_usd is not None:
                confidence += 0.30
            if round_type != "undisclosed":
                confidence += 0.15
            if investors:
                confidence += 0.10
            if is_official_source:
                confidence += 0.15

            signals.append(
                FundingSignal(
                    round_type=round_type,
                    amount_usd=amount_usd,
                    amount_as_published=as_published,
                    currency=currency,
                    investors=list(dict.fromkeys(investors)),
                    lead_investor=lead,
                    quote=sentence[:500],
                    confidence=round(min(1.0, confidence), 2),
                    announced_at=published_at,
                )
            )

        return self._deduplicate(signals)

    @staticmethod
    def _deduplicate(signals: Sequence[FundingSignal]) -> List[FundingSignal]:
        """Collapse repeats of one announcement within a single document."""
        seen: Dict[tuple, FundingSignal] = {}
        for signal in signals:
            key = (signal.round_type, signal.amount_as_published)
            existing = seen.get(key)
            if existing is None or signal.confidence > existing.confidence:
                seen[key] = signal
        return list(seen.values())

    @staticmethod
    def summarize(rounds: Iterable[Any]) -> Dict[str, Any]:
        """Aggregate stored rounds into an outreach-relevant view."""
        rounds = list(rounds)
        disclosed = [r for r in rounds if getattr(r, "amount_usd", None)]
        total = sum(float(r.amount_usd) for r in disclosed)

        cfg = settings.FUNDING
        if total >= cfg.strong_raise_usd:
            band = "well_funded"
        elif total >= cfg.material_raise_usd:
            band = "materially_funded"
        elif disclosed:
            band = "lightly_funded"
        elif rounds:
            band = "raised_amount_undisclosed"
        else:
            band = "no_public_funding_evidence"

        investors: List[str] = []
        for r in rounds:
            investors.extend(getattr(r, "investors", []) or [])

        latest = None
        dated = [r for r in rounds if getattr(r, "announced_at", None)]
        if dated:
            latest = max(dated, key=lambda r: r.announced_at)

        return {
            "band": band,
            "total_disclosed_usd": total or None,
            "rounds_recorded": len(rounds),
            "rounds_with_disclosed_amount": len(disclosed),
            "latest_round_type": getattr(latest, "round_type", None),
            "latest_announced_at": (
                latest.announced_at.isoformat() if latest and latest.announced_at else None
            ),
            "investors": sorted(dict.fromkeys(investors))[:20],
            # Stated explicitly so no downstream consumer reads a missing total
            # as "raised nothing".
            "note": (
                "Only publicly announced figures are recorded. An absent total means "
                "no disclosed round was found, not that the project is unfunded."
            ),
        }


funding_extractor = FundingExtractor()
