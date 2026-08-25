"""Tests for Registry, GitHub, Web, and ATS collectors."""

from datetime import datetime, timezone
import pytest
from src.collectors.ats.job_boards import ATSJobBoardsCollector
from src.collectors.github.hyper_search import GitHubHyperSearchCollector
from src.collectors.registries.chainid_network import ChainIdNetworkCollector
from src.collectors.registries.cosmos_registry import CosmosRegistryCollector
from src.collectors.registries.ethereum_lists import EthereumListsCollector
from src.collectors.registries.superchain import SuperchainCollector
from src.core.types import LifecycleStage, NetworkEnvironment, RawItem, StackFamily


def test_ethereum_lists_normalization():
    collector = EthereumListsCollector()
    raw = RawItem(
        source_id="ethereum_lists",
        external_id="1",
        url="http://gh.com/chains/1",
        source_family="registry",
        raw_payload={
            "chainId": 1001,
            "name": "SuperL2 Mainnet",
            "rpc": ["https://rpc.superl2.org"],
            "explorers": [{"url": "https://explorer.superl2.org"}],
            "infoURL": "https://superl2.org",
            "status": "active",
        },
        content_hash="h1",
    )
    obs = collector.normalize(raw)
    assert len(obs) == 1
    assert obs[0].candidate_name == "SuperL2 Mainnet"
    assert obs[0].human_chain_id == "1001"
    assert obs[0].caip2 == "eip155:1001"
    assert obs[0].environment == NetworkEnvironment.MAINNET
    assert "superl2.org" in obs[0].organization_domains


def test_cosmos_registry_normalization():
    collector = CosmosRegistryCollector()
    raw = RawItem(
        source_id="cosmos_chain_registry",
        external_id="cos1",
        url="http://gh.com/cosmos/osmosis",
        source_family="registry",
        raw_payload={
            "chain_name": "osmosis",
            "pretty_name": "Osmosis",
            "chain_id": "osmosis-1",
            "network_type": "mainnet",
            "website": "https://osmosis.zone",
            "apis": {"rpc": [{"address": "https://rpc.osmosis.zone"}]},
        },
        content_hash="hcos",
    )
    obs = collector.normalize(raw)
    assert len(obs) == 1
    assert obs[0].candidate_name == "Osmosis"
    assert obs[0].stack_family == StackFamily.COSMOS
    assert obs[0].caip2 == "cosmos:osmosis-1"


def test_ats_job_board_normalization():
    collector = ATSJobBoardsCollector()
    raw = RawItem(
        source_id="ats_job_boards",
        external_id="ats_1",
        url="https://boards.greenhouse.io/kora/jobs/123",
        source_family="careers",
        raw_payload={
            "platform": "greenhouse",
            "slug": "kora",
            "org_name": "Kora Foundation",
            "title": "Head of Community - Africa",
            "location": "Lagos, Nigeria",
            "url": "https://boards.greenhouse.io/kora/jobs/123",
        },
        content_hash="hats",
    )
    obs = collector.normalize(raw)
    assert len(obs) == 1
    assert obs[0].candidate_name == "Kora Foundation"
    assert len(obs[0].opportunities) == 1
    assert obs[0].opportunities[0]["signal_strength"] == 1.0
    assert "Nigeria" in obs[0].opportunities[0]["geography"]
