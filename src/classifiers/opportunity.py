"""Opportunity classifier mapping signals into actionable engagement strategies."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from src.core.types import OpportunityType


OPPORTUNITY_PATTERNS = [
    (
        OpportunityType.COMMUNITY_OPERATIONS,
        re.compile(r"\b(community manager|moderator|chapter|local language|event organizer|contributor program)\b", re.IGNORECASE),
        "Community-as-a-service proposal",
    ),
    (
        OpportunityType.DEVELOPER_RELATIONS,
        re.compile(r"\b(devrel|developer relations|developer advocate|hackathon|sdk workshop|developer bootcamp)\b", re.IGNORECASE),
        "Developer onboarding and university/hub program",
    ),
    (
        OpportunityType.MARKET_ENTRY_BD,
        re.compile(r"\b(country manager|regional lead|partnership|go-to-market|market entry|business development|exchange listing)\b", re.IGNORECASE),
        "Country launch and partnership map",
    ),
    (
        OpportunityType.AMBASSADOR_GRANTS,
        re.compile(r"\b(ambassador|ambassador program|ecosystem grants|rfp|bounty|grant cohort)\b", re.IGNORECASE),
        "Operate or recruit an Africa cohort",
    ),
    (
        OpportunityType.VALIDATOR_INFRASTRUCTURE,
        re.compile(r"\b(genesis validator|validator onboarding|node operator|rpc provider|indexer coverage|node latency)\b", re.IGNORECASE),
        "Africa validator/RPC/infrastructure partnership",
    ),
    (
        OpportunityType.ADOPTION_USER_ACQUISITION,
        re.compile(r"\b(merchant|payment gateway|mobile money|remittance|wallet integration|local rails|liquidity program)\b", re.IGNORECASE),
        "Measured pilot with defined acquisition KPIs",
    ),
    (
        OpportunityType.POLICY_ENTERPRISE,
        re.compile(r"\b(government|central bank|telecom|regulator|enterprise pilot|public-sector)\b", re.IGNORECASE),
        "Stakeholder engagement and compliant pilot",
    ),
    (
        OpportunityType.INVESTMENT_MA,
        re.compile(r"\b(ecosystem fund|strategic investment|venture fund|formal acquisition)\b", re.IGNORECASE),
        "Route to qualified advisory; never infer sale intent",
    ),
]


class OpportunityClassifier:
    """Classifies opportunities and pairs them with recommended Ashinity responses."""

    @staticmethod
    def classify(text: str) -> List[Tuple[OpportunityType, str, str]]:
        """Identifies opportunity types, matched snippets, and suggested responses.
        
        Returns:
            List[Tuple[OpportunityType, suggested_response, matched_text]]
        """
        results = []
        for opp_type, pattern, response in OPPORTUNITY_PATTERNS:
            match = pattern.search(text)
            if match:
                results.append((opp_type, response, match.group(0)))
        return results


opportunity_classifier = OpportunityClassifier()
