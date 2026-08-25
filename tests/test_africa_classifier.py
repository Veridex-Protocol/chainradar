"""Africa intent and market-fit classifier (spec 11, 12, acceptance tests 11-12)."""

import pytest

from src.classifiers.africa import africa_classifier
from src.core.types import AfricaIntentLabel


def test_country_lexicon_coverage():
    assert len(africa_classifier.lex.countries) == 54


def test_priority_hubs_rails_and_currencies():
    text = (
        "We are integrating M-Pesa payments for Nairobi merchants "
        "and deploying NGN stablecoins in Lagos."
    )
    geo = africa_classifier.extract_geography(text)

    assert "Kenya" in geo.countries
    assert "Nigeria" in geo.countries
    assert "Nairobi" in geo.hubs and "Lagos" in geo.hubs
    assert "NGN" in geo.currencies
    assert any("pesa" in rail.lower() or "mobile money" in rail.lower() for rail in geo.rails)


def test_economic_blocs_extraction():
    text = "Facilitating cross-border settlement under AfCFTA and ECOWAS guidelines."
    geo = africa_classifier.extract_geography(text)
    assert "AfCFTA" in geo.blocs
    assert "ECOWAS" in geo.blocs


# --------------------------------------------------------------------------
# Ambiguity set (spec 25: "avoid known ambiguity set")
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Chad Wilson joined as our new head of engineering.",
        "Our investor Mali Chen led the seed round.",
        "The Togo release ships next quarter.",
        "Benchmarks were run on a Guinea pig cluster in Frankfurt.",
        "Congo Square Ventures participated in the round.",
    ],
)
def test_ambiguous_country_names_alone_are_not_geography(text):
    """A bare 'Chad' or 'Mali' is a person, not a market.

    These surface forms only count when the document carries corroborating
    African context; otherwise they are recorded as rejected so an analyst can
    see what was considered and dropped.
    """
    geo = africa_classifier.extract_geography(text)
    assert not geo.countries, f"expected no country match, got {sorted(geo.countries)}"
    assert geo.rejected_ambiguous, "the near-miss should be recorded, not silently dropped"

    _vector, label = africa_classifier.evaluate_feature_vector(text, is_official_source=True)
    assert label in (AfricaIntentLabel.A4_NO_EVIDENCE, AfricaIntentLabel.A3_AFRICA_COMPATIBLE)


def test_ambiguous_names_count_with_african_context():
    """With real African context, the same surface form is a genuine match."""
    text = "Expanding our West Africa operations across Mali, Niger and Senegal."
    geo = africa_classifier.extract_geography(text)
    assert "Senegal" in geo.countries          # unambiguous, licenses the rest
    assert "Mali" in geo.countries
    assert "Niger" in geo.countries
    assert not geo.rejected_ambiguous


def test_niger_does_not_match_inside_nigeria():
    geo = africa_classifier.extract_geography("Our Lagos office serves Nigeria.")
    assert "Nigeria" in geo.countries
    assert "Niger" not in geo.countries


# --------------------------------------------------------------------------
# Label hierarchy
# --------------------------------------------------------------------------

def test_intent_label_hierarchy():
    a1 = (
        "Official Foundation roadmap: expansion to Nigeria and Kenya with local "
        "developer grants and a validator cohort."
    )
    _, label = africa_classifier.evaluate_feature_vector(a1, is_official_source=True)
    assert label == AfricaIntentLabel.A1_EXPLICIT_INTENT

    a2 = "Deploying local community hackathons across Lagos and Accra with MoMo payment integration."
    _, label = africa_classifier.evaluate_feature_vector(a2, is_official_source=False)
    assert label in (AfricaIntentLabel.A1_EXPLICIT_INTENT, AfricaIntentLabel.A2_ACTIVE_REGIONAL_MOTION)

    a3 = (
        "Global decentralized remittance and cross-border stablecoin micropayments "
        "architecture for emerging markets."
    )
    _, label = africa_classifier.evaluate_feature_vector(a3, is_official_source=True)
    assert label == AfricaIntentLabel.A3_AFRICA_COMPATIBLE

    a4 = "General purpose EVM rollup for high frequency on-chain gaming."
    _, label = africa_classifier.evaluate_feature_vector(a4, is_official_source=True)
    assert label == AfricaIntentLabel.A4_NO_EVIDENCE


def test_explicit_intent_requires_an_official_source():
    """A1 asserts the project said it; a blog rumour cannot establish that.

    The `is_official_source` flag also defaults to False, so a caller that
    forgets it falls back to the weaker claim rather than the stronger one.
    """
    text = "Rumour: the team is hiring a country manager for Nigeria and Kenya."

    _, unofficial = africa_classifier.evaluate_feature_vector(text)  # default False
    assert unofficial != AfricaIntentLabel.A1_EXPLICIT_INTENT

    _, official = africa_classifier.evaluate_feature_vector(text, is_official_source=True)
    assert official == AfricaIntentLabel.A1_EXPLICIT_INTENT


def test_generic_global_language_cannot_exceed_a3():
    """Acceptance test 11: a generic 'global' statement never becomes intent."""
    text = (
        "We are building a global, borderless payments network for everyone, "
        "everywhere, with worldwide scale and international reach."
    )
    _, label = africa_classifier.evaluate_feature_vector(text, is_official_source=True)
    assert label in (AfricaIntentLabel.A3_AFRICA_COMPATIBLE, AfricaIntentLabel.A4_NO_EVIDENCE)


# --------------------------------------------------------------------------
# Scoring honesty
# --------------------------------------------------------------------------

def test_unobserved_readiness_components_score_zero():
    """No Africa evidence must not yield a large Africa score.

    whitespace/contactability/operating_capacity describe an opportunity. If
    they defaulted to their maxima, every candidate would carry 35 points of
    africa_fit - 0.35 of the outreach score - on no evidence at all.
    """
    vector, label = africa_classifier.evaluate_feature_vector(
        "General purpose EVM rollup for on-chain gaming.", is_official_source=True
    )
    assert label == AfricaIntentLabel.A4_NO_EVIDENCE
    assert vector.whitespace == 0.0
    assert vector.contactability == 0.0
    assert vector.operating_capacity == 0.0
    assert vector.total_score == 0.0
    assert vector.confidence == 0.0


def test_observed_readiness_components_do_score():
    vector, _ = africa_classifier.evaluate_feature_vector(
        "Foundation roadmap: launching in Nigeria with a community manager and grants.",
        is_official_source=True,
        has_local_team=False,
        has_public_contact=True,
        has_funding_or_activity=True,
    )
    assert vector.whitespace == 15.0
    assert vector.contactability == 10.0
    assert vector.operating_capacity == 10.0
    assert vector.total_score > 60.0


def test_regional_action_requires_geography():
    """Generic hiring language with no region is not regional action."""
    vector, _ = africa_classifier.evaluate_feature_vector(
        "We are hiring a community manager and a business development lead.",
        is_official_source=True,
    )
    assert vector.regional_action == 0.0


def test_a5_already_covered_when_local_team_exists():
    vector, label = africa_classifier.evaluate_feature_vector(
        "Our Lagos team runs the Nigeria ambassador programme.",
        is_official_source=True,
        has_local_team=True,
    )
    assert label == AfricaIntentLabel.A5_ALREADY_COVERED
    assert vector.whitespace == 3.0, "an existing local team leaves little whitespace"


# --------------------------------------------------------------------------
# Per-country sub-scores (spec 12)
# --------------------------------------------------------------------------

def test_per_country_subscores_are_not_collapsed_to_one_number():
    """"A payments chain may fit Nigeria and Kenya for different reasons"."""
    text = (
        "Official roadmap: launching M-Pesa integration in Nairobi, Kenya, and "
        "recruiting a country manager for Lagos, Nigeria."
    )
    scores = africa_classifier.per_country_scores(text, is_official_source=True)

    assert {"Kenya", "Nigeria"} <= set(scores)
    assert scores["Kenya"]["iso2"] == "KE"
    assert scores["Nigeria"]["is_priority_market"] is True
    assert "Nairobi" in scores["Kenya"]["matched_hubs"]
    assert "Lagos" in scores["Nigeria"]["matched_hubs"]
    assert all(0.0 < s["strength"] <= 1.0 for s in scores.values())


def test_multilingual_matching_tolerates_stripped_diacritics():
    """Lexicons keep exact diacritics; sources frequently do not."""
    with_accents = africa_classifier.extract_geography(
        "Expansion en Afrique: recrutement d'un responsable pour le Nigéria."
    )
    without_accents = africa_classifier.extract_geography(
        "Expansion en Afrique: recrutement d'un responsable pour le Nigeria."
    )
    assert "Nigeria" in with_accents.countries
    assert "Nigeria" in without_accents.countries
