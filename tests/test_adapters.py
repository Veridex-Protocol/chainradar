"""Tests for EVM, CometBFT, Substrate, SVM, Starknet, Aptos, Sui, and Fuel Protocol Adapters."""

import pytest
from src.core.normalizer import format_caip2
from src.core.types import HeadObservation, NetworkIdentity
from src.verifier.engine import verifier_engine


def test_protocol_adapters_registered():
    families = ["evm", "cosmos", "substrate", "svm", "starknet", "aptos", "sui", "fuel"]
    for fam in families:
        adapter = verifier_engine.get_adapter(fam)
        assert adapter is not None
        assert adapter.family == fam


def test_caip2_formatting_across_families():
    assert format_caip2("eip155", "1") == "eip155:1"
    assert format_caip2("eip155", "987654") == "eip155:987654"
    assert format_caip2("cosmos", "osmosis-1") == "cosmos:osmosis-1"
    assert format_caip2("polkadot", "91b171bb158e2d3848fa23a9f1c25182") == "polkadot:91b171bb158e2d3848fa23a9f1c25182"
    assert format_caip2("solana", "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp") == "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
    assert format_caip2("starknet", "SN_MAIN") == "starknet:SN_MAIN"
    assert format_caip2("aptos", "1") == "aptos:1"
    assert format_caip2("sui", "35834a8a") == "sui:35834a8a"
    assert format_caip2("fuel", "9889") == "fuel:9889"
