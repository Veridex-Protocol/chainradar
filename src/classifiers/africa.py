"""Africa intent and market-fit classifier (spec 11, 12).

Two rules shape this module.

*Explicit intent is not inferred fit.* A1/A2 describe what the project itself
said or did; A3 is an Ashinity hypothesis about suitability. The two are scored
from different evidence and can never be produced by the same code path, so the
engine cannot quietly upgrade "this chain would suit Nigeria" into "this chain
is going to Nigeria".

*Absence of evidence scores zero.* The readiness components (whitespace,
contactability, operating capacity) describe an opportunity, so they are only
awarded when something was actually observed. Defaulting them to full marks
would hand every candidate a large Africa score with no Africa evidence at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from src.config import lexicons, settings
from src.core.types import AfricaFeatureVector, AfricaIntentLabel

# Unambiguous pan-African terms. The presence of any one of these is enough to
# license an otherwise ambiguous country surface form such as "Chad".
_PAN_AFRICA = re.compile(
    r"\b(africa|african|afrique|africain|africaine|áfrica|africano|africana|afrika|"
    r"sub-saharan|subsaharan|maghreb|afcfta|ecowas|cedeao|sadc|comesa|eac|"
    r"african union|union africaine)\b",
    re.IGNORECASE | re.UNICODE,
)


def _strip_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _normalize(text: str) -> str:
    """NFKC + casefold, preserving diacritics and native script."""
    return unicodedata.normalize("NFKC", text or "").casefold()


def _term_pattern(term: str) -> re.Pattern:
    """Word-boundary matcher tolerant of internal whitespace runs."""
    escaped = r"\s+".join(re.escape(part) for part in term.split())
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE | re.UNICODE)


def _matches(term: str, haystack: str, folded_haystack: str) -> bool:
    """Match a term against the text, also trying a diacritic-folded form.

    Lexicon entries keep their exact diacritics (spec 11 requires it), but
    sources routinely strip them - "Nigeria" for "Nigéria", "Cote d'Ivoire" for
    "Côte d'Ivoire" - so recall is widened without loosening the lexicon.
    """
    if _term_pattern(term).search(haystack):
        return True
    folded_term = _strip_diacritics(term)
    if folded_term != term and _term_pattern(folded_term).search(folded_haystack):
        return True
    return False


@dataclass
class GeoMatch:
    """Everything the geographic pass found, with per-country attribution."""

    countries: Dict[str, Set[str]] = field(default_factory=dict)   # country -> surface forms
    regions: Set[str] = field(default_factory=set)
    blocs: Set[str] = field(default_factory=set)
    hubs: Dict[str, str] = field(default_factory=dict)             # city -> country
    currencies: Set[str] = field(default_factory=set)
    rails: Set[str] = field(default_factory=set)
    languages: Set[str] = field(default_factory=set)
    rejected_ambiguous: Dict[str, str] = field(default_factory=dict)  # form -> country

    @property
    def has_unambiguous_geography(self) -> bool:
        return bool(self.countries or self.regions or self.blocs or self.hubs)


@dataclass
class IntentMatch:
    """Which intent packs fired, and on what terms."""

    packs: Dict[str, List[str]] = field(default_factory=dict)

    def fired(self, *names: str) -> bool:
        return any(self.packs.get(n) for n in names)

    @property
    def all_terms(self) -> List[str]:
        return sorted({t for terms in self.packs.values() for t in terms})


class AfricaClassifier:
    """Classifies Africa expansion intent versus inferred compatibility."""

    def __init__(self) -> None:
        self.lex = lexicons

    # -- geography ---------------------------------------------------------
    def extract_geography(self, text: str) -> GeoMatch:
        norm = _normalize(text)
        folded = _strip_diacritics(norm)
        result = GeoMatch()
        if not norm.strip():
            return result

        has_pan_african_context = bool(_PAN_AFRICA.search(norm) or _PAN_AFRICA.search(folded))
        ambiguous_forms = self.lex.ambiguous_surface_forms

        # Pass 1: unambiguous surface forms only. This establishes whether the
        # document is about Africa at all, which pass 2 depends on.
        pending_ambiguous: Dict[str, Set[str]] = {}
        for country in self.lex.countries:
            name = country["name"]
            surface_forms = [name, *country.get("aliases", []), *country.get("demonyms", [])]
            for form in surface_forms:
                if not form:
                    continue
                if not _matches(form, norm, folded):
                    continue
                if form.casefold() in ambiguous_forms:
                    pending_ambiguous.setdefault(name, set()).add(form)
                else:
                    result.countries.setdefault(name, set()).add(form)

        for region_name in self.lex.regions:
            if _matches(region_name, norm, folded):
                result.regions.add(region_name)
        if has_pan_african_context:
            result.regions.add("Pan-Africa")

        for bloc_code, bloc in self.lex.economic_blocs.items():
            forms = [bloc_code, *bloc.get("aliases", [])]
            if any(_matches(f, norm, folded) for f in forms if f):
                result.blocs.add(bloc_code)

        for hub in self.lex.priority_hubs:
            if _matches(hub["city"], norm, folded):
                result.hubs[hub["city"]] = hub["country"]
                result.countries.setdefault(hub["country"], set()).add(hub["city"])

        for currency in self.lex.currencies:
            if _term_pattern(currency["code"]).search(text or ""):  # currency codes are case-sensitive
                result.currencies.add(currency["code"])

        for rail in self.lex.payment_rails:
            if _matches(rail, norm, folded):
                result.rails.add(rail)

        for lang_code, lang_pack in self.lex.languages.items():
            terms = list(lang_pack.get("intent_terms", [])) + list(lang_pack.get("geography_terms", []))
            if any(_matches(t, norm, folded) for t in terms if t):
                result.languages.add(lang_code)

        # Pass 2: an ambiguous form counts only with corroborating African
        # context - a pan-African term, another country, a bloc or a hub.
        corroborated = (
            has_pan_african_context
            or bool(result.countries)
            or bool(result.blocs)
            or bool(result.hubs)
            or bool(result.currencies)
        )
        for country_name, forms in pending_ambiguous.items():
            if corroborated:
                result.countries.setdefault(country_name, set()).update(forms)
            else:
                for form in forms:
                    result.rejected_ambiguous[form] = country_name

        return result

    # -- intent ------------------------------------------------------------
    def extract_intent(self, text: str) -> IntentMatch:
        norm = _normalize(text)
        folded = _strip_diacritics(norm)
        match = IntentMatch()
        for pack_name, pack in self.lex.intent_packs.items():
            hits = [t for t in pack.get("terms", []) if t and _matches(t, norm, folded)]
            if hits:
                match.packs[pack_name] = hits
        return match

    # -- public API --------------------------------------------------------
    def evaluate_feature_vector(
        self,
        text: str,
        is_official_source: bool = False,
        has_local_team: Optional[bool] = None,
        has_public_contact: Optional[bool] = None,
        has_funding_or_activity: Optional[bool] = None,
    ) -> Tuple[AfricaFeatureVector, AfricaIntentLabel]:
        """Score the Africa feature vector and assign an A1-A5 label.

        `is_official_source` defaults to **False**: A1/A2 assert that the
        project itself said something, so a caller that forgets the flag must
        fall back to the weaker claim, never the stronger one.

        The readiness flags default to `None`, meaning "not observed", and
        score zero. Passing an explicit True/False records a real observation.
        """
        geo = self.extract_geography(text)
        intent = self.extract_intent(text)
        norm = _normalize(text)
        folded = _strip_diacritics(norm)

        require_evidence = settings.africa_requires_evidence_for_explicit_intent

        # 1. explicit_geo (0-30) - only official sources can max this out.
        explicit_geo = 0.0
        if geo.countries or geo.hubs:
            explicit_geo = 30.0 if is_official_source else 15.0
        elif geo.regions or geo.blocs:
            explicit_geo = 20.0 if is_official_source else 10.0

        # 2. regional_action (0-20) - a concrete act, not an adjective.
        regional_action = 0.0
        if intent.fired("hiring", "market_entry"):
            regional_action += 12.0
        if intent.fired("programs", "partnership"):
            regional_action += 8.0
        if geo.rails or geo.currencies:
            regional_action += 8.0
        regional_action = min(20.0, regional_action)
        # A regional *action* requires a region. Without geography this is just
        # generic company activity and must not score.
        if not geo.has_unambiguous_geography:
            regional_action = 0.0

        # 3. use_case_fit (0-15) - the one component that is legitimately an
        #    inference about suitability rather than a project claim.
        use_case_terms = {
            "payments", "stablecoin", "remittance", "mobile money", "financial inclusion",
            "depin", "rwa", "identity", "cross-border", "merchant", "microfinance",
            "trade finance", "off-ramp", "on-ramp",
        }
        use_case_hits = sorted(t for t in use_case_terms if _matches(t, norm, folded))
        use_case_fit = min(15.0, 5.0 * len(use_case_hits)) if use_case_hits else 0.0

        # 4-6. Readiness components: unobserved means zero, never full marks.
        whitespace = 0.0 if has_local_team is None else (15.0 if not has_local_team else 3.0)
        contactability = 0.0 if has_public_contact is None else (10.0 if has_public_contact else 0.0)
        operating_capacity = (
            0.0 if has_funding_or_activity is None else (10.0 if has_funding_or_activity else 3.0)
        )

        total = min(
            100.0,
            explicit_geo + regional_action + use_case_fit + whitespace + contactability + operating_capacity,
        )

        label = self._assign_label(
            geo=geo,
            intent=intent,
            is_official_source=is_official_source,
            require_evidence=require_evidence,
            has_local_team=has_local_team,
            use_case_fit=use_case_fit,
            regional_action=regional_action,
        )

        confidence = self._confidence(geo, is_official_source, label)

        vector = AfricaFeatureVector(
            explicit_geo=explicit_geo,
            regional_action=regional_action,
            use_case_fit=use_case_fit,
            whitespace=whitespace,
            contactability=contactability,
            operating_capacity=operating_capacity,
            total_score=total,
            matched_countries=sorted(geo.countries),
            matched_regions=sorted(geo.regions | geo.blocs),
            matched_languages=sorted(geo.languages),
            matched_rails=sorted(geo.rails | geo.currencies),
            evidence_snippets=self._snippets(text, geo, intent),
            confidence=confidence,
        )
        return vector, label

    def per_country_scores(self, text: str, is_official_source: bool = False) -> Dict[str, Dict[str, Any]]:
        """Per-country and per-region sub-scores (spec 12).

        "A payments chain may fit Nigeria and Kenya for different reasons", so
        the engine keeps a breakdown per market instead of one continent-wide
        number that cannot be acted on.
        """
        geo = self.extract_geography(text)
        intent = self.extract_intent(text)
        priority = set(settings.AFRICA_PRIORITY_MARKETS or [])

        out: Dict[str, Dict[str, Any]] = {}
        for country_name, forms in geo.countries.items():
            record = self.lex.country_by_name.get(country_name.lower(), {})
            iso2 = record.get("iso2", "")
            hubs = [city for city, owner in geo.hubs.items() if owner == country_name]
            out[country_name] = {
                "iso2": iso2,
                "region": record.get("region"),
                "is_priority_market": iso2 in priority,
                "matched_surface_forms": sorted(forms),
                "matched_hubs": hubs,
                "intent_packs": sorted(k for k, v in intent.packs.items() if v),
                # Named directly, plus a hub, plus intent language is a much
                # stronger country-level claim than a passing mention.
                "strength": round(
                    min(1.0, 0.4 + 0.2 * bool(hubs) + 0.2 * bool(intent.packs) + 0.2 * is_official_source),
                    2,
                ),
            }
        return out

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _assign_label(
        *,
        geo: GeoMatch,
        intent: IntentMatch,
        is_official_source: bool,
        require_evidence: bool,
        has_local_team: Optional[bool],
        use_case_fit: float,
        regional_action: float,
    ) -> AfricaIntentLabel:
        has_geo = geo.has_unambiguous_geography

        # A5: already covered - a verified local team/partner footprint.
        if has_local_team and has_geo:
            return AfricaIntentLabel.A5_ALREADY_COVERED

        # A1: the project itself named Africa or a country in an official
        # context alongside a concrete intent. Requires an official source
        # whenever the configuration demands evidence for explicit intent.
        official_ok = is_official_source or not require_evidence
        if official_ok and has_geo and intent.fired("hiring", "market_entry", "programs", "partnership"):
            return AfricaIntentLabel.A1_EXPLICIT_INTENT

        # A2: repeated/observable regional motion - local rails, local-language
        # content, campaigns - even without an explicit strategy statement.
        if has_geo and (regional_action >= 8.0 or geo.rails or geo.currencies or len(geo.languages) > 1):
            return AfricaIntentLabel.A2_ACTIVE_REGIONAL_MOTION

        # A3: our own suitability hypothesis. Deliberately reachable without
        # any geography - that is exactly what makes it a hypothesis.
        if use_case_fit >= 5.0:
            return AfricaIntentLabel.A3_AFRICA_COMPATIBLE

        if has_geo:
            return AfricaIntentLabel.A3_AFRICA_COMPATIBLE

        return AfricaIntentLabel.A4_NO_EVIDENCE

    @staticmethod
    def _confidence(geo: GeoMatch, is_official_source: bool, label: AfricaIntentLabel) -> float:
        if label == AfricaIntentLabel.A4_NO_EVIDENCE:
            return 0.0
        base = 0.45
        if geo.countries or geo.hubs:
            base += 0.25
        elif geo.regions or geo.blocs:
            base += 0.15
        if is_official_source:
            base += 0.20
        if geo.rejected_ambiguous:
            # Something looked like a country but could not be corroborated.
            base -= 0.10
        return round(max(0.0, min(1.0, base)), 2)

    @staticmethod
    def _snippets(text: str, geo: GeoMatch, intent: IntentMatch, limit: int = 5) -> List[str]:
        """Short verbatim spans supporting the label, for the evidence card."""
        if not text:
            return []
        needles = (
            [f for forms in geo.countries.values() for f in forms]
            + sorted(geo.regions)
            + sorted(geo.blocs)
            + sorted(geo.hubs)
            + sorted(geo.rails)
            + intent.all_terms
        )
        if not needles:
            return []
        snippets: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lowered = _strip_diacritics(stripped.casefold())
            if any(_strip_diacritics(n.casefold()) in lowered for n in needles):
                # Capped so stored quotes stay within source licensing limits.
                snippets.append(stripped[:200])
            if len(snippets) >= limit:
                break
        return snippets


africa_classifier = AfricaClassifier()
