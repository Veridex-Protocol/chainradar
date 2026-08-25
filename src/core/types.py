"""Core domain types, enums, and Pydantic DTOs for the Early Chain Discovery Engine."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LifecycleStage(str, Enum):
    S0_RESEARCH_HINT = "S0_research_hint"
    S1_DEVNET_PROTOTYPE = "S1_devnet_prototype"
    S2_PUBLIC_TESTNET = "S2_public_testnet"
    S3_INCENTIVIZED_TESTNET = "S3_incentivized_testnet"
    S4_MAINNET_ANNOUNCED = "S4_mainnet_announced"
    S5_EARLY_MAINNET = "S5_early_mainnet"
    S6_ESTABLISHED_ARCHIVED = "S6_established_archived"


class StackFamily(str, Enum):
    EVM = "evm"
    COSMOS = "cosmos"
    SUBSTRATE = "substrate"
    SVM = "svm"
    STARKNET = "starknet"
    MOVE = "move"
    FUEL = "fuel"
    CUSTOM = "custom"


class NetworkEnvironment(str, Enum):
    DEVNET = "devnet"
    TESTNET = "testnet"
    MAINNET = "mainnet"
    EPHEMERAL = "ephemeral"
    LOCAL = "local"
    UNKNOWN = "unknown"


class IncarnationStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"
    DEAD = "dead"


class AfricaIntentLabel(str, Enum):
    A1_EXPLICIT_INTENT = "A1_explicit_intent"
    A2_ACTIVE_REGIONAL_MOTION = "A2_active_regional_motion"
    A3_AFRICA_COMPATIBLE = "A3_africa_compatible"
    A4_NO_EVIDENCE = "A4_no_evidence"
    A5_ALREADY_COVERED = "A5_already_covered"


class CandidateState(str, Enum):
    HOT = "HOT"
    QUALIFIED = "QUALIFIED"
    RADAR = "RADAR"
    STALE = "STALE"
    REJECT = "REJECT"


class WorkflowState(str, Enum):
    NEW = "NEW"
    VERIFYING = "VERIFYING"
    RADAR = "RADAR"
    QUALIFIED = "QUALIFIED"
    APPROVED = "APPROVED"
    CONTACTED = "CONTACTED"
    ENGAGED = "ENGAGED"
    NURTURE = "NURTURE"
    REJECTED = "REJECTED"


class OpportunityType(str, Enum):
    COMMUNITY_OPERATIONS = "community_operations"
    DEVELOPER_RELATIONS = "developer_relations"
    MARKET_ENTRY_BD = "market_entry_bd"
    AMBASSADOR_GRANTS = "ambassador_grants"
    VALIDATOR_INFRASTRUCTURE = "validator_infrastructure"
    ADOPTION_USER_ACQUISITION = "adoption_user_acquisition"
    POLICY_ENTERPRISE = "policy_enterprise"
    INVESTMENT_MA = "investment_ma"


class RateBudget(BaseModel):
    remaining_requests: int = 60
    reset_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cost_per_request: int = 1


class Cursor(BaseModel):
    source_id: str
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    last_seen_sha: Optional[str] = None
    last_seen_timestamp: Optional[datetime] = None
    page: int = 1
    cursor_token: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class RawItem(BaseModel):
    source_id: str
    external_id: str
    url: str
    source_family: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None
    raw_payload: Any
    headers: Dict[str, str] = Field(default_factory=dict)
    content_hash: str
    provenance: Dict[str, Any] = Field(default_factory=dict)


class FetchBatch(BaseModel):
    source_id: str
    items: List[RawItem] = Field(default_factory=list)
    next_cursor: Cursor
    provenance: Dict[str, Any] = Field(default_factory=dict)


class RawObservation(BaseModel):
    candidate_name: str
    candidate_slug: Optional[str] = None
    organization_name: Optional[str] = None
    organization_domains: List[str] = Field(default_factory=list)
    github_orgs: List[str] = Field(default_factory=list)
    social_handles: Dict[str, str] = Field(default_factory=dict)
    claimed_locations: List[str] = Field(default_factory=list)
    
    stack_family: StackFamily = StackFamily.EVM
    stack_details: Optional[str] = None
    layer: Optional[str] = None
    purpose_labels: List[str] = Field(default_factory=list)
    
    environment: NetworkEnvironment = NetworkEnvironment.TESTNET
    is_public: bool = True
    caip2: Optional[str] = None
    protocol_namespace: Optional[str] = None
    human_chain_id: Optional[str] = None
    rpc_urls: List[str] = Field(default_factory=list)
    explorer_urls: List[str] = Field(default_factory=list)
    faucet_urls: List[str] = Field(default_factory=list)
    genesis_fingerprint: Optional[str] = None
    genesis_time: Optional[datetime] = None
    
    stage: LifecycleStage = LifecycleStage.S0_RESEARCH_HINT
    raw_text: Optional[str] = None
    claims: Dict[str, Any] = Field(default_factory=dict)
    contacts: List[Dict[str, Any]] = Field(default_factory=list)
    opportunities: List[Dict[str, Any]] = Field(default_factory=list)
    parser_version: str = "1.0.0"
    reliability: float = 0.85


class NetworkIdentity(BaseModel):
    protocol_namespace: str
    chain_id: str
    display_caip2: str
    client_version: Optional[str] = None
    spec_version: Optional[str] = None
    genesis_hash: Optional[str] = None
    genesis_time: Optional[datetime] = None
    block0_hash: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class HeadObservation(BaseModel):
    block_height: int
    block_hash: Optional[str] = None
    block_time: Optional[datetime] = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GenesisEvidence(BaseModel):
    genesis_hash: str
    genesis_time: Optional[datetime] = None
    block0_hash: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class VerificationResult(BaseModel):
    endpoint: str
    success: bool
    identity: Optional[NetworkIdentity] = None
    head: Optional[HeadObservation] = None
    genesis: Optional[GenesisEvidence] = None
    error_type: Optional[str] = None
    error_detail: Optional[str] = None
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AfricaFeatureVector(BaseModel):
    explicit_geo: float = 0.0          # 0..30
    regional_action: float = 0.0       # 0..20
    use_case_fit: float = 0.0          # 0..15
    whitespace: float = 0.0            # 0..15
    contactability: float = 0.0        # 0..10
    operating_capacity: float = 0.0    # 0..10
    total_score: float = 0.0           # 0..100
    matched_countries: List[str] = Field(default_factory=list)
    matched_regions: List[str] = Field(default_factory=list)
    matched_languages: List[str] = Field(default_factory=list)
    matched_rails: List[str] = Field(default_factory=list)
    evidence_snippets: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class ScoreBreakdown(BaseModel):
    confidence: float                  # C: 0..100
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict)
    momentum: float                    # M: 0..100
    momentum_breakdown: Dict[str, float] = Field(default_factory=dict)
    africa_fit: float                  # A: 0..100
    risk: float                        # R: 0..100 (penalties)
    risk_breakdown: Dict[str, float] = Field(default_factory=dict)
    radar_score: float                 # 0.40*M + 0.35*C + 0.25*A
    outreach_score: float              # 0.45*C + 0.35*A + 0.20*M - 0.30*R
    outreach_gate_passed: bool
    gate_failures: List[str] = Field(default_factory=list)
    state: CandidateState
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    rule_version: str = "v1.0"
