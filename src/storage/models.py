"""SQLAlchemy 2 async models for the Early Chain Discovery & Africa Intelligence Engine."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


def generate_uuid() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceEvent(Base):
    """Immutable, append-only raw evidence ledger."""
    __tablename__ = "evidence_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    source_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source_family: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    raw_payload_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    extracted_claims: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    reliability: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    observation_links = relationship("ObservationLink", back_populates="evidence", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_source_external_id"),
        UniqueConstraint("source_id", "content_hash", name="uq_source_content_hash"),
    )


class Organization(Base):
    """Canonical organization entity."""
    __tablename__ = "organizations"

    org_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    official_domains: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    github_orgs: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    social_handles: Mapped[Dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    claimed_locations: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    foundation_form: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    aliases: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    chains = relationship("ChainProduct", back_populates="organization", lazy="selectin")
    contacts = relationship("Contact", back_populates="organization", lazy="selectin")


class ChainProduct(Base):
    """Logical blockchain product."""
    __tablename__ = "chain_products"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.org_id"), index=True, nullable=True)
    canonical_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    aliases: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    purpose_labels: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    stack_family: Mapped[str] = mapped_column(String(64), default="evm", index=True, nullable=False)
    stack_details: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    layer: Mapped[Optional[str]] = mapped_column(String(32), default="L2", nullable=True)
    parent_chain: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    settlement_chain: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    da_layer: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    stage: Mapped[str] = mapped_column(String(64), default="S0_research_hint", index=True, nullable=False)
    
    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    repo_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_commit_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    domain_first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registry_pr_opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registry_merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    testnet_announced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mainnet_announced_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mainnet_live_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    organization = relationship("Organization", back_populates="chains", lazy="selectin")
    networks = relationship("Network", back_populates="chain_product", cascade="all, delete-orphan", lazy="selectin")
    assessment = relationship("AfricaAssessment", back_populates="chain_product", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    score = relationship("ScoreSnapshot", back_populates="chain_product", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    signals = relationship("Signal", back_populates="chain_product", cascade="all, delete-orphan", lazy="selectin")
    opportunities = relationship("Opportunity", back_populates="chain_product", cascade="all, delete-orphan", lazy="selectin")
    contacts = relationship("Contact", back_populates="chain_product", cascade="all, delete-orphan", lazy="selectin")
    observation_links = relationship("ObservationLink", back_populates="chain_product", cascade="all, delete-orphan", lazy="selectin")


class Network(Base):
    """Network environment for a chain product (e.g. Sepolia testnet vs Mainnet)."""
    __tablename__ = "networks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    chain_product_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), index=True, nullable=False)
    environment: Mapped[str] = mapped_column(String(32), default="testnet", index=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    caip2: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    protocol_namespace: Mapped[Optional[str]] = mapped_column(String(64), default="eip155", nullable=True)
    human_chain_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    rpc_urls: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    explorer_urls: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    faucet_urls: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    launch_claims: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    chain_product = relationship("ChainProduct", back_populates="networks", lazy="selectin")
    incarnations = relationship("NetworkIncarnation", back_populates="network", cascade="all, delete-orphan", lazy="selectin")


class NetworkIncarnation(Base):
    """Technical fingerprint and lifecycle instance for a network."""
    __tablename__ = "network_incarnations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    network_id: Mapped[str] = mapped_column(String(64), ForeignKey("networks.id"), index=True, nullable=False)
    genesis_fingerprint: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    genesis_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    block0_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    first_observed_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_observed_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True, nullable=False)
    superseded_by_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    network = relationship("Network", back_populates="incarnations", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("network_id", "genesis_fingerprint", name="uq_network_genesis"),
    )


class ObservationLink(Base):
    """Provenance edge connecting raw evidence to derived candidate chains."""
    __tablename__ = "observation_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    evidence_id: Mapped[str] = mapped_column(String(64), ForeignKey("evidence_events.id"), index=True, nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), index=True, nullable=False)
    link_type: Mapped[str] = mapped_column(String(64), default="primary_discovery", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    evidence = relationship("EvidenceEvent", back_populates="observation_links", lazy="selectin")
    chain_product = relationship("ChainProduct", back_populates="observation_links", lazy="selectin")


class Signal(Base):
    """Extracted atomic signals with lifecycle implications."""
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    candidate_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), index=True, nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), default="positive", nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    lifecycle_implication: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)

    chain_product = relationship("ChainProduct", back_populates="signals", lazy="selectin")


class Opportunity(Base):
    """Categorized commercial and partnership opportunities."""
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    candidate_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), index=True, nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    geography: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    chain_product = relationship("ChainProduct", back_populates="opportunities", lazy="selectin")


class AfricaAssessment(Base):
    """Africa Intent & Regional Readiness assessment."""
    __tablename__ = "africa_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    candidate_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), unique=True, index=True, nullable=False)
    intent_label: Mapped[str] = mapped_column(String(32), default="A4_no_evidence", index=True, nullable=False)
    readiness: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    whitespace: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)
    countries: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    regions: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    languages: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    rails_use_cases: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_ids: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    # Vector Sub-Scores
    explicit_geo_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    regional_action_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    use_case_fit_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    whitespace_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    contactability_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    operating_capacity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    
    analyst_override: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    chain_product = relationship("ChainProduct", back_populates="assessment", lazy="selectin")


class Contact(Base):
    """Enriched public business contact with strict compliance & suppression."""
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    org_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("organizations.org_id"), index=True, nullable=True)
    candidate_id: Mapped[Optional[str]] = mapped_column(String(64), ForeignKey("chain_products.id"), index=True, nullable=True)
    role_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    channel_type: Mapped[str] = mapped_column(String(32), default="form", nullable=False)
    channel_value: Mapped[str] = mapped_column(String(512), nullable=False)
    channel_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    permitted_purpose: Mapped[str] = mapped_column(String(255), default="partnership_inquiry", nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    suppression_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    organization = relationship("Organization", back_populates="contacts", lazy="selectin")
    chain_product = relationship("ChainProduct", back_populates="contacts", lazy="selectin")


class ScoreSnapshot(Base):
    """Explainable score snapshot and workflow qualification state."""
    __tablename__ = "score_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    candidate_id: Mapped[str] = mapped_column(String(64), ForeignKey("chain_products.id"), unique=True, index=True, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    momentum: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    africa_fit: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    radar_score: Mapped[float] = mapped_column(Float, default=0.0, index=True, nullable=False)
    outreach_score: Mapped[float] = mapped_column(Float, default=0.0, index=True, nullable=False)
    outreach_qualified: Mapped[bool] = mapped_column(Boolean, default=False, index=True, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="RADAR", index=True, nullable=False)
    workflow_state: Mapped[str] = mapped_column(String(32), default="NEW", index=True, nullable=False)
    feature_vector: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), default="v1.0", nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)

    chain_product = relationship("ChainProduct", back_populates="score", lazy="selectin")


class SourceCursor(Base):
    """Tracks collector cursors, ETags, and health status."""
    __tablename__ = "source_cursors"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cursor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    safe_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_success: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class AuditLog(Base):
    """Full audit trail for config changes, analyst decisions, and contact actions."""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=generate_uuid)
    actor: Mapped[str] = mapped_column(String(128), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    before_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    after_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
