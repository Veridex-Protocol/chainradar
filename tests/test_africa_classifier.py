"""Tests for the Africa Intent & Market-Fit Classifier."""

import pytest
from src.classifiers.africa import africa_classifier
from src.core.types import AfricaIntentLabel


def test_country_lexicon_coverage():
    assert len(africa_classifier.lex.countries) == 54


def test_priority_hubs_and_rails():
    text = "We are integrating M-Pesa payments for Nairobi merchants and deploying NGN stablecoins in Lagos."
    countries, regions, hubs, currencies, rails = africa_classifier.extract_matches(text)

    assert "Kenya" in countries
    assert "Nigeria" in countries
    assert "Nairobi" in hubs
    assert "Lagos" in hubs
    assert "NGN" in currencies
    assert "m-pesa" in rails or "mpesa" in rails or "mobile money" in rails


def test_economic_blocs_extraction():
    text = "Facilitating cross-border settlement under AfCFTA and ECOWAS guidelines."
    countries, regions, hubs, currencies, rails = africa_classifier.extract_matches(text)

    assert "AfCFTA" in regions
    assert "ECOWAS" in regions


def test_intent_label_hierarchy():
    # A1: Explicit Official Intent
    t_a1 = "Official Foundation roadmap: Expansion to Nigeria and Kenya with local developer grants and validator cohort."
    vec_a1, label_a1 = africa_classifier.evaluate_feature_vector(t_a1, is_official_source=True)
    assert label_a1 == AfricaIntentLabel.A1_EXPLICIT_INTENT

    # A2: Active Regional Motion
    t_a2 = "Deploying local community hackathons across Lagos and Accra with MoMo payment integration."
    vec_a2, label_a2 = africa_classifier.evaluate_feature_vector(t_a2, is_official_source=False)
    assert label_a2 in (AfricaIntentLabel.A1_EXPLICIT_INTENT, AfricaIntentLabel.A2_ACTIVE_REGIONAL_MOTION)

    # A3: Africa-Compatible Use Case
    t_a3 = "Global decentralized remittance and cross-border stablecoin micropayments architecture for emerging markets."
    vec_a3, label_a3 = africa_classifier.evaluate_feature_vector(t_a3, is_official_source=True)
    assert label_a3 == AfricaIntentLabel.A3_AFRICA_COMPATIBLE

    # A4: No Evidence
    t_a4 = "General purpose EVM rollup for high frequency on-chain gaming."
    vec_a4, label_a4 = africa_classifier.evaluate_feature_vector(t_a4, is_official_source=True)
    assert label_a4 == AfricaIntentLabel.A4_NO_EVIDENCE
