export interface Candidate {
  id: string;
  name: string;
  slug: string;
  organization: string;
  stage: string;
  stack_family: string;
  layer: string;
  first_seen_at: string;
  last_verified_at: string | null;
  africa_label: string;
  africa_score: number;
  scores: {
    outreach_score: number;
    radar_score: number;
    confidence: number;
    risk: number;
    state: string;
    workflow_state?: string;
  };
}

export interface DetailedCandidate {
  header: {
    canonical_name: string;
    organization: string;
    official_domains: string[];
    stage: string;
    purpose_labels: string[];
  };
  why_now: {
    highlight: string;
    recent_signals_count: number;
    lifecycle_summary: string;
  };
  identity: {
    caip2: string;
    chain_id: string;
    genesis_fingerprint: string;
    rpc_urls: string[];
    explorer_urls: string[];
  };
  africa: {
    label: string;
    confidence: number;
    score: number;
    countries: string[];
    regions: string[];
    sub_scores: {
      explicit_geo: number;
      regional_action: number;
      use_case_fit: number;
      whitespace: number;
      contactability: number;
      operating_capacity: number;
    };
  };
  scores: {
    outreach_score: number;
    radar_score: number;
    confidence: number;
    momentum: number;
    africa_fit?: number;
    risk: number;
    state: string;
    workflow_state: string;
  };
  recommendation: string;
  opportunities: Array<{
    type: string;
    summary: string;
    geography: string;
  }>;
  people_and_channels: Array<{
    role: string;
    channel_type: string;
    value: string;
    permitted_purpose: string;
  }>;
  evidence: Array<{
    id: string;
    source_id: string;
    url: string;
    observed_at: string;
  }>;
}

export interface Source {
  source_id: string;
  name: string;
  family: string;
  tier: string;
  reliability: number;
  cadence: string;
  last_sync: string | null;
  kill_switch: boolean;
}
