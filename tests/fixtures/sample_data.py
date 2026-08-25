"""Test fixtures and mock payloads for Acceptance Tests and Backtesting."""

from datetime import datetime, timezone

# 1. Registry PR Fixtures
REGISTRY_PR_FIXTURE_1 = {
    "pr_number": 4201,
    "title": "Add Kora Network testnet (chainId: 987654)",
    "body": """
    Adding Kora Network Sepolia Testnet.
    Chain ID: 987654
    RPC: https://rpc.testnet.kora.network
    Explorer: https://explorer.testnet.kora.network
    Info: https://kora.network
    We are launching developer grants for African builders in Nigeria and Kenya.
    """,
    "state": "open",
    "created_at": "2026-08-01T10:00:00Z",
    "updated_at": "2026-08-01T10:00:00Z",
    "user": "kora-dev",
    "html_url": "https://github.com/ethereum-lists/chains/pull/4201",
}

REGISTRY_PR_UPDATE_FIXTURE = {
    "pr_number": 4201,
    "title": "Add Kora Network testnet (chainId: 987654) - Updated RPC",
    "body": """
    Adding Kora Network Sepolia Testnet.
    Chain ID: 987654
    RPC: https://new-rpc.testnet.kora.network
    Explorer: https://explorer.testnet.kora.network
    Info: https://kora.network
    We are launching developer grants for African builders in Nigeria and Kenya.
    """,
    "state": "open",
    "created_at": "2026-08-01T10:00:00Z",
    "updated_at": "2026-08-02T14:30:00Z",
    "user": "kora-dev",
    "html_url": "https://github.com/ethereum-lists/chains/pull/4201",
}

REGISTRY_PR_MERGE_FIXTURE = {
    "pr_number": 4201,
    "title": "Add Kora Network testnet (chainId: 987654)",
    "body": "Merged Kora Network testnet.",
    "state": "closed",
    "created_at": "2026-08-01T10:00:00Z",
    "updated_at": "2026-08-03T18:00:00Z",
    "merged_at": "2026-08-03T18:00:00Z",
    "user": "kora-dev",
    "html_url": "https://github.com/ethereum-lists/chains/pull/4201",
}

# 2. Africa Intent Fixtures
AFRICA_OFFICIAL_JOB_TEXT = """
Optimism Foundation is hiring an Africa Lead / Country Manager based in Lagos, Nigeria or Nairobi, Kenya.
Responsible for regional developer relations, ecosystem grants, and fintech integrations with M-Pesa and NGN payment rails.
"""

GENERIC_GLOBAL_TEXT = """
Nexus Chain is a high-performance EVM Layer 2 rollup for global decentralized finance, gaming, and decentralized social applications.
"""

FRENCH_REGIONAL_TEXT = """
Lancement de Baobab Chain au Sénégal et en Côte d'Ivoire. Programme d'ambassadeurs et subventions pour développeurs francophones.
"""

PORTUGUESE_REGIONAL_TEXT = """
A rede Zâmbia Chain expande para Angola e Moçambique com programa de bolsas para desenvolvedores comunitários.
"""

ARABIC_REGIONAL_TEXT = """
إطلاق شبكة النيل في مصر وشمال أفريقيا لدعم الشراكات الإقليمية وعلاقات المطورين.
"""

SWAHILI_REGIONAL_TEXT = """
Mtandao wa Kilimanjaro unazindua mpango wa ruzuku za watengenezaji nchini Kenya na Tanzania kwa malipo ya M-Pesa.
"""

TOKEN_ONLY_TEXT = """
Buy SuperMoon Token on Uniswap! 100x potential ERC-20 meme coin with zero tax and liquidity locked. No chain, just tokenomics.
"""

# Positive and Negative Corpus for Backtesting
POSITIVE_CORPUS = [
    {
        "name": f"KnownChain_{i}",
        "first_eligible_signal": f"2026-01-{(i%28)+1:02d}T00:00:00Z",
        "mainnet_live_at": f"2026-06-{(i%28)+1:02d}T00:00:00Z",
        "sample_text": f"KnownChain_{i} public testnet and developer grants for Africa expansion in Nigeria (Lagos)." if i % 2 == 0 else f"KnownChain_{i} Layer 2 mainnet beta announcement.",
        "expected_africa_label": "A1_explicit_intent" if i % 2 == 0 else "A3_africa_compatible",
        "verified_genesis": True,
    }
    for i in range(1, 51)
]

NEGATIVE_CORPUS = [
    {
        "name": f"MemeToken_{i}",
        "first_eligible_signal": f"2026-02-{(i%28)+1:02d}T00:00:00Z",
        "is_token_only": True,
        "sample_text": f"MemeToken_{i} presale on PancakeSwap, token contract 0x12345.",
    }
    for i in range(1, 151)
]
