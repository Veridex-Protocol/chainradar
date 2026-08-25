"""Africa Intent & Market-Fit Classifier with 6-component feature vector and A1-A5 labeling."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple
from src.config import lexicons
from src.core.types import AfricaFeatureVector, AfricaIntentLabel


class AfricaClassifier:
    """Classifies Africa expansion intent vs. inferred compatibility using multi-language lexicons."""

    def __init__(self):
        self.lex = lexicons

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        # Preserve diacritics where needed for French/Portuguese, but NFKC normalize
        return unicodedata.normalize("NFKC", text).lower()

    def extract_matches(self, text: str) -> Tuple[List[str], List[str], List[str], List[str], List[str]]:
        """Extracts matched countries, regions, economic blocs, hubs, currencies, and rails.
        
        Returns:
            Tuple[countries, regions_and_blocs, priority_hubs, currencies, payment_rails]
        """
        norm = self._normalize_text(text)
        matched_countries: Set[str] = set()
        matched_regions: Set[str] = set()
        matched_hubs: Set[str] = set()
        matched_currencies: Set[str] = set()
        matched_rails: Set[str] = set()

        # 1. Countries & Aliases
        for c in self.lex.countries:
            c_name = c["name"].lower()
            if re.search(rf"\b{re.escape(c_name)}\b", norm):
                matched_countries.add(c["name"])
            for alias in c.get("aliases", []):
                if re.search(rf"\b{re.escape(alias.lower())}\b", norm):
                    matched_countries.add(c["name"])
            for demonym in c.get("demonyms", []):
                if re.search(rf"\b{re.escape(demonym.lower())}\b", norm):
                    matched_countries.add(c["name"])

        # 2. Regions & Blocs
        for r_name, r_countries in self.lex.regions.items():
            if re.search(rf"\b{re.escape(r_name.lower())}\b", norm):
                matched_regions.add(r_name)
        if re.search(r"\b(africa|african|afrique|africain|africaine|áfrica|africano|afrika)\b", norm):
            matched_regions.add("Pan-Africa")

        for b_code, b_val in self.lex.economic_blocs.items():
            if re.search(rf"\b{re.escape(b_code.lower())}\b", norm):
                matched_regions.add(b_code)
            for b_alias in b_val.get("aliases", []):
                if re.search(rf"\b{re.escape(b_alias.lower())}\b", norm):
                    matched_regions.add(b_code)

        # 3. Priority Hubs
        for hub in self.lex.priority_hubs:
            h_city = hub["city"].lower()
            if re.search(rf"\b{re.escape(h_city)}\b", norm):
                matched_hubs.add(hub["city"])
                matched_countries.add(hub["country"])

        # 4. Currencies
        for curr in self.lex.currencies:
            c_code = curr["code"].lower()
            if re.search(rf"\b{re.escape(c_code)}\b", norm):
                matched_currencies.add(curr["code"])

        # 5. Payment Rails
        for rail in self.lex.payment_rails:
            if re.search(rf"\b{re.escape(rail.lower())}\b", norm):
                matched_rails.add(rail)

        return (
            sorted(list(matched_countries)),
            sorted(list(matched_regions)),
            sorted(list(matched_hubs)),
            sorted(list(matched_currencies)),
            sorted(list(matched_rails)),
        )

    def evaluate_feature_vector(
        self,
        text: str,
        is_official_source: bool = True,
        has_local_team: bool = False,
        has_public_contact: bool = True,
        has_funding_or_activity: bool = True,
    ) -> Tuple[AfricaFeatureVector, AfricaIntentLabel]:
        """Calculates the 6-component Africa feature vector and deterministic label."""
        norm = self._normalize_text(text)
        countries, regions, hubs, currencies, rails = self.extract_matches(text)

        has_geo = bool(countries or regions or hubs)
        
        # Check intent packs
        has_hiring = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("hiring", {}).get("terms", []))
        has_programs = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("programs", {}).get("terms", []))
        has_market_entry = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("market_entry", {}).get("terms", []))
        has_adoption = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("adoption", {}).get("terms", []))
        has_partnership = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("partnership", {}).get("terms", []))
        has_capital = any(re.search(rf"\b{re.escape(t)}\b", norm) for t in self.lex.intent_packs.get("capital", {}).get("terms", []))

        # Check multi-language terms
        matched_languages: Set[str] = set()
        for lang_code, lang_pack in self.lex.languages.items():
            if any(t in norm for t in lang_pack.get("intent_terms", [])):
                matched_languages.add(lang_code)

        # 1. explicit_geo (0..30)
        explicit_geo = 0.0
        if has_geo and is_official_source:
            if countries or hubs:
                explicit_geo = 30.0
            elif regions:
                explicit_geo = 20.0
        elif has_geo:
            explicit_geo = 15.0

        # 2. regional_action (0..20)
        regional_action = 0.0
        if has_hiring or has_market_entry:
            regional_action += 12.0
        if has_programs or has_partnership:
            regional_action += 8.0
        if rails or currencies:
            regional_action += 8.0
        regional_action = min(20.0, regional_action)

        # 3. use_case_fit (0..15)
        use_case_fit = 0.0
        if has_adoption or rails or currencies:
            use_case_fit += 10.0
        if any(w in norm for w in ["remittance", "payments", "mobile money", "financial inclusion", "depin", "rwa", "stablecoin"]):
            use_case_fit += 5.0
        use_case_fit = min(15.0, use_case_fit)

        # 4. whitespace (0..15)
        whitespace = 15.0 if not has_local_team else 5.0

        # 5. contactability (0..10)
        contactability = 10.0 if has_public_contact else 4.0

        # 6. operating_capacity (0..10)
        operating_capacity = 10.0 if has_funding_or_activity else 5.0

        total_score = min(100.0, explicit_geo + regional_action + use_case_fit + whitespace + contactability + operating_capacity)

        # Snippets extraction
        snippets = []
        for line in text.split("\n"):
            l_norm = line.lower()
            if any(c.lower() in l_norm for c in countries) or any(r.lower() in l_norm for r in regions) or any(rail in l_norm for rail in rails):
                snippets.append(line.strip()[:200])

        confidence = 0.90 if is_official_source and has_geo else (0.75 if has_geo else 0.40)

        vec = AfricaFeatureVector(
            explicit_geo=explicit_geo,
            regional_action=regional_action,
            use_case_fit=use_case_fit,
            whitespace=whitespace,
            contactability=contactability,
            operating_capacity=operating_capacity,
            total_score=total_score,
            matched_countries=countries,
            matched_regions=regions,
            matched_languages=sorted(list(matched_languages)),
            matched_rails=sorted(list(set(rails + currencies))),
            evidence_snippets=snippets[:5],
            confidence=confidence,
        )

        # Label Assignment (Section 11)
        if has_local_team and total_score >= 60:
            label = AfricaIntentLabel.A5_ALREADY_COVERED
        elif is_official_source and has_geo and (has_hiring or has_market_entry or has_programs or has_partnership):
            label = AfricaIntentLabel.A1_EXPLICIT_INTENT
        elif (has_geo and (regional_action >= 10.0 or rails)) or (regional_action >= 15.0 and len(matched_languages) > 1):
            label = AfricaIntentLabel.A2_ACTIVE_REGIONAL_MOTION
        elif use_case_fit >= 8.0:
            # Compatible but no explicit origin claim
            label = AfricaIntentLabel.A3_AFRICA_COMPATIBLE
        else:
            label = AfricaIntentLabel.A4_NO_EVIDENCE

        return vec, label


africa_classifier = AfricaClassifier()
