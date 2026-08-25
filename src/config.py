"""Configuration management for the Early Chain Discovery & Africa Intelligence Engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RateLimitConfig(BaseModel):
    requests_per_minute: int = 60
    burst: int = 10


class SourceConfig(BaseModel):
    source_id: str
    name: str
    family: str
    tier: str = "A"
    owner: str = ""
    terms_url: str = ""
    access_method: str = "http_get"
    fields_stored: List[str] = Field(default_factory=list)
    retention_days: int = 365
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    kill_switch: bool = False
    reliability: float = 0.85
    cadence: str = "*/15 * * * *"


class AlertThresholds(BaseModel):
    confidence_min: float = 75.0
    priority_min: float = 70.0
    risk_max: float = 34.0


class QualifiedThresholds(BaseModel):
    confidence_min: float = 65.0
    priority_min: float = 55.0


class RadarThresholds(BaseModel):
    radar_min: float = 45.0


class AlertConfig(BaseModel):
    hot: AlertThresholds = Field(default_factory=AlertThresholds)
    qualified: QualifiedThresholds = Field(default_factory=QualifiedThresholds)
    radar: RadarThresholds = Field(default_factory=RadarThresholds)


class ScoreWeights(BaseModel):
    radar_momentum: float = 0.40
    radar_confidence: float = 0.35
    radar_africa_fit: float = 0.25

    outreach_confidence: float = 0.45
    outreach_africa_fit: float = 0.35
    outreach_momentum: float = 0.20
    outreach_risk_penalty: float = 0.30


class VerifyConfig(BaseModel):
    """Endpoint safety and network controls (spec 15).

    These are data, not constants in code: an operator must be able to widen a
    port or tighten a timeout without a redeploy of the verifier.
    """

    allowed_schemes: List[str] = Field(default_factory=lambda: ["https"])
    # http is permitted only for these explicitly listed public hosts.
    allow_http_hosts: List[str] = Field(default_factory=list)
    allowed_ports: List[int] = Field(default_factory=lambda: [80, 443, 8545, 8546, 26657, 9944, 8899, 9650, 4000])
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 5.0
    max_response_bytes: int = 2_000_000
    # 0 means: do not follow redirects at all (spec 15 default).
    max_redirects: int = 0
    per_domain_concurrency: int = 2
    per_domain_rate_per_minute: int = 30
    jitter_seconds: float = 0.25
    liveness_recheck_min_seconds: int = 60
    liveness_recheck_max_seconds: int = 180


class FreshnessConfig(BaseModel):
    """Per-signal-type freshness half-lives in days (spec 17 'decay by signal type')."""

    half_life_days: Dict[str, float] = Field(
        default_factory=lambda: {
            "registry": 21.0,
            "official_web": 14.0,
            "code_search": 10.0,
            "infrastructure": 21.0,
            "careers": 30.0,
            "news": 7.0,
            "social": 3.0,
            "market": 30.0,
            "verification": 7.0,
            "standards": 45.0,
            "explorer": 21.0,
            "interop": 21.0,
            "default": 14.0,
        }
    )


class StalenessConfig(BaseModel):
    """Stage-specific evidence TTLs driving the STALE state (spec 17)."""

    days_by_stage: Dict[str, int] = Field(
        default_factory=lambda: {
            "S0_research_hint": 30,
            "S1_devnet_prototype": 45,
            "S2_public_testnet": 21,
            "S3_incentivized_testnet": 14,
            "S4_mainnet_announced": 14,
            "S5_early_mainnet": 21,
            "S6_established_archived": 90,
        }
    )


class OutreachGateConfig(BaseModel):
    """Hard promotion gate (spec 01, 17)."""

    confidence_min: float = 65.0
    require_official_attribution: bool = True
    min_independent_source_families: int = 2
    allow_technical_verified_override: bool = True


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core Environment
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "development-secret-key-change-in-production"
    TIMEZONE_DISPLAY: str = "Africa/Lagos"
    STORAGE_TIMEZONE: str = "UTC"

    # Database & Storage
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/chains.db"
    OBJECT_STORE_PATH: str = "./data/raw_evidence"
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"
    REDIS_ENABLED: bool = False

    # Optional S3 Storage
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None

    # Platform Credentials
    GITHUB_TOKEN: Optional[str] = None
    BRAVE_API_KEY: Optional[str] = None
    X_API_TOKEN: Optional[str] = None
    NEYNAR_API_KEY: Optional[str] = None
    REDDIT_CLIENT_ID: Optional[str] = None
    REDDIT_CLIENT_SECRET: Optional[str] = None
    COINGECKO_API_KEY: Optional[str] = None

    # Alerting & Webhooks
    ALERT_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None

    # Windows & Defaults
    EARLY_MAINNET_DAYS: int = 180
    EVIDENCE_RETENTION_DAYS: int = 365
    CONTACT_INACTIVITY_DAYS: int = 90
    GITHUB_SEARCH_OVERLAP_HOURS: int = 72
    NIGHTLY_BACKFILL_DAYS: int = 14
    RPC_LIVENESS_RECHECK_SECONDS: int = 120
    DEDUP_WINDOW_HOURS: int = 24
    HUMAN_APPROVAL_BEFORE_OUTREACH: bool = True

    # Scoring & Weights
    SCORE_WEIGHTS: ScoreWeights = Field(default_factory=ScoreWeights)
    ALERTS: AlertConfig = Field(default_factory=AlertConfig)
    VERIFY: VerifyConfig = Field(default_factory=VerifyConfig)
    FRESHNESS: FreshnessConfig = Field(default_factory=FreshnessConfig)
    STALENESS: StalenessConfig = Field(default_factory=StalenessConfig)
    OUTREACH_GATE: OutreachGateConfig = Field(default_factory=OutreachGateConfig)
    # Derived hash of the YAML config; stamped onto every score snapshot so a
    # threshold change is visible in the audit trail (spec 20 rule versioning).
    RULE_VERSION: str = "v1.0"


class Lexicons:
    """Holds structured lexicon data loaded from config/lexicons."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.countries: List[Dict[str, Any]] = []
        self.country_by_name: Dict[str, Dict[str, Any]] = {}
        self.country_by_iso2: Dict[str, Dict[str, Any]] = {}
        self.country_by_iso3: Dict[str, Dict[str, Any]] = {}
        self.regions: Dict[str, List[str]] = {}
        self.economic_blocs: Dict[str, Dict[str, Any]] = {}
        self.priority_hubs: List[Dict[str, Any]] = []
        self.currencies: List[Dict[str, Any]] = []
        self.payment_rails: List[str] = []
        self.languages: Dict[str, Dict[str, Any]] = {}
        self.intent_packs: Dict[str, Dict[str, Any]] = {}
        self.job_role_patterns: List[str] = []
        self.load()

    def load(self) -> None:
        lexicon_dir = self.base_path / "lexicons"
        if not lexicon_dir.exists():
            return

        # Countries
        countries_file = lexicon_dir / "countries.json"
        if countries_file.exists():
            with open(countries_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.countries = data.get("countries", [])
                for c in self.countries:
                    name_key = c["name"].lower()
                    self.country_by_name[name_key] = c
                    self.country_by_iso2[c["iso2"].upper()] = c
                    self.country_by_iso3[c["iso3"].upper()] = c
                    for alias in c.get("aliases", []):
                        self.country_by_name[alias.lower()] = c

        # Regions and Blocs
        rb_file = lexicon_dir / "regions_and_blocs.json"
        if rb_file.exists():
            with open(rb_file, "r", encoding="utf-8") as f:
                rb_data = json.load(f)
                self.regions = rb_data.get("regions", {})
                self.economic_blocs = rb_data.get("economic_blocs", {})

        # Hubs and Rails
        hr_file = lexicon_dir / "hubs_and_rails.json"
        if hr_file.exists():
            with open(hr_file, "r", encoding="utf-8") as f:
                hr_data = json.load(f)
                self.priority_hubs = hr_data.get("priority_hubs", [])
                self.currencies = hr_data.get("currencies", [])
                self.payment_rails = hr_data.get("payment_rails", [])

        # Languages
        lang_file = lexicon_dir / "languages.json"
        if lang_file.exists():
            with open(lang_file, "r", encoding="utf-8") as f:
                lang_data = json.load(f)
                self.languages = lang_data.get("languages", {})

        # Intent Keywords
        intent_file = lexicon_dir / "intent_keywords.json"
        if intent_file.exists():
            with open(intent_file, "r", encoding="utf-8") as f:
                intent_data = json.load(f)
                self.intent_packs = intent_data.get("intent_packs", {})
                self.job_role_patterns = intent_data.get("job_role_patterns", [])


class SourceRegister:
    """Loads and manages source registry configurations and kill switches."""

    def __init__(self, config_file: Path):
        self.config_file = config_file
        self.sources: Dict[str, SourceConfig] = {}
        self.load()

    def load(self) -> None:
        if not self.config_file.exists():
            return
        with open(self.config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            source_list = data.get("sources", [])
            for item in source_list:
                src = SourceConfig(**item)
                self.sources[src.source_id] = src

    def get(self, source_id: str) -> Optional[SourceConfig]:
        return self.sources.get(source_id)

    def is_enabled(self, source_id: str) -> bool:
        src = self.sources.get(source_id)
        if not src:
            return False
        return not src.kill_switch

    def set_kill_switch(self, source_id: str, disabled: bool) -> bool:
        if source_id in self.sources:
            self.sources[source_id].kill_switch = disabled
            return True
        return False


# ---------------------------------------------------------------------------
# YAML overlay
# ---------------------------------------------------------------------------
# `default_config.yaml` is the authored source of truth for thresholds,
# windows, weights and lexicon policy. Environment variables still win, so a
# deployment can override a single value without editing the file.


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_yaml_config(config_dir: Path) -> Dict[str, Any]:
    """Load and merge every *.yaml in the config directory (excluding registers)."""
    merged: Dict[str, Any] = {}
    skip = {"source_register.yaml", "query_packs.yaml"}
    for path in sorted(config_dir.glob("*.yaml")):
        if path.name in skip:
            continue
        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        if not isinstance(doc, dict):
            raise ValueError(f"config file {path} must contain a mapping at the top level")
        merged = _deep_merge(merged, doc)
    return merged


def _apply_yaml_overlay(base: "AppSettings", doc: Dict[str, Any]) -> "AppSettings":
    """Project the YAML document onto AppSettings fields."""
    if not doc:
        return base

    values = base.model_dump()
    system = doc.get("system", {}) or {}
    windows = doc.get("windows", {}) or {}

    mapping = {
        "TIMEZONE_DISPLAY": system.get("timezone_display"),
        "STORAGE_TIMEZONE": system.get("storage_timezone"),
        "EARLY_MAINNET_DAYS": system.get("early_mainnet_days"),
        "EVIDENCE_RETENTION_DAYS": system.get("evidence_retention_days"),
        "CONTACT_INACTIVITY_DAYS": system.get("contact_inactivity_days"),
        "HUMAN_APPROVAL_BEFORE_OUTREACH": system.get("human_approval_before_outreach"),
        "OBJECT_STORE_PATH": system.get("object_store_path"),
        "GITHUB_SEARCH_OVERLAP_HOURS": windows.get("github_search_overlap_hours"),
        "NIGHTLY_BACKFILL_DAYS": windows.get("nightly_backfill_days"),
        "RPC_LIVENESS_RECHECK_SECONDS": windows.get("rpc_liveness_recheck_seconds"),
        "DEDUP_WINDOW_HOURS": windows.get("dedup_window_hours"),
    }
    for key, val in mapping.items():
        if val is not None:
            values[key] = val

    if doc.get("database", {}).get("url"):
        values["DATABASE_URL"] = doc["database"]["url"]
    if doc.get("redis", {}).get("url"):
        values["REDIS_URL"] = doc["redis"]["url"]
    if "enabled" in (doc.get("redis") or {}):
        values["REDIS_ENABLED"] = doc["redis"]["enabled"]

    if doc.get("alerts"):
        values["ALERTS"] = _deep_merge(values.get("ALERTS") or {}, doc["alerts"])
    if doc.get("weights"):
        w = doc["weights"]
        flat = {}
        for k, v in (w.get("radar") or {}).items():
            flat[f"radar_{k}"] = v
        for k, v in (w.get("outreach") or {}).items():
            flat[f"outreach_{k}"] = v
        values["SCORE_WEIGHTS"] = _deep_merge(values.get("SCORE_WEIGHTS") or {}, flat)
    for key, section in (
        ("VERIFY", "verify"),
        ("FRESHNESS", "freshness"),
        ("STALENESS", "staleness"),
        ("OUTREACH_GATE", "outreach_gate"),
    ):
        if doc.get(section):
            values[key] = _deep_merge(values.get(key) or {}, doc[section])

    # The rule version is derived from the merged document, so any threshold
    # change produces a new version on every score written afterwards.
    digest = hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:12]
    values["RULE_VERSION"] = f"v1.0+{digest}"

    # Environment variables must still win over the YAML overlay.
    env_overrides = {
        name: getattr(base, name)
        for name in base.model_fields
        if name in os.environ or name.lower() in os.environ
    }
    values.update(env_overrides)
    return AppSettings(**values)


# Global singletons
_project_root = Path(__file__).resolve().parent.parent
_config_dir = _project_root / "config"

settings = _apply_yaml_overlay(AppSettings(), load_yaml_config(_config_dir))
lexicons = Lexicons(_config_dir)
source_register = SourceRegister(_config_dir / "source_register.yaml")
