"""Evidence Card builder and export formatter for human analysts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from src.storage.models import ChainProduct, EvidenceEvent


class EvidenceCardBuilder:
    """Renders the comprehensive 10-section Evidence Card for analysts."""

    @staticmethod
    def build_card(chain: ChainProduct, evidence_list: List[EvidenceEvent]) -> Dict[str, Any]:
        org_name = chain.organization.display_name if chain.organization else (chain.canonical_name or "Unknown Org")
        domains = chain.organization.official_domains if chain.organization else []
        
        # Primary network
        primary_net = chain.networks[0] if chain.networks else None
        caip2 = primary_net.caip2 if primary_net else f"{chain.stack_family}:{chain.slug}"
        chain_id = primary_net.human_chain_id if primary_net else None
        
        # Genesis fingerprint
        genesis_fp = "pending_probe"
        if primary_net and primary_net.incarnations:
            genesis_fp = primary_net.incarnations[0].genesis_fingerprint

        # Africa Assessment
        africa = chain.assessment
        africa_label = africa.intent_label if africa else "A4_no_evidence"
        africa_score = africa.total_score if africa else 0.0
        countries = africa.countries if africa else []
        regions = africa.regions if africa else []

        # Opportunities
        opp_list = []
        if chain.opportunities:
            for opp in chain.opportunities:
                opp_list.append({
                    "type": opp.opportunity_type,
                    "geography": opp.geography,
                    "summary": opp.summary,
                })

        # Contacts
        contact_list = []
        if chain.contacts:
            for c in chain.contacts:
                if not c.suppressed:
                    contact_list.append({
                        "role": c.role_type,
                        "channel_type": c.channel_type,
                        "value": c.channel_value,
                        "permitted_purpose": c.permitted_purpose,
                        "source_url": c.source_url,
                    })

        # Funding Rounds (Spec 13 'Capital')
        funding_list = []
        total_funding_usd = 0.0
        for f in (chain.funding_rounds or []):
            if f.amount_usd:
                total_funding_usd += float(f.amount_usd)
            funding_list.append({
                "round_type": f.round_type,
                "amount_usd": f.amount_usd,
                "amount_as_published": f.amount_as_published,
                "lead_investor": f.lead_investor,
                "investors": f.investors,
                "announced_at": f.announced_at.isoformat() if f.announced_at else None,
                "source_url": f.source_url,
                "quote": f.quote,
                "confidence": f.confidence,
            })

        # Scores
        score_obj = chain.score
        scores = {
            "confidence": score_obj.confidence if score_obj else 0.0,
            "momentum": score_obj.momentum if score_obj else 0.0,
            "africa_fit": score_obj.africa_fit if score_obj else 0.0,
            "risk": score_obj.risk if score_obj else 0.0,
            "radar_score": score_obj.radar_score if score_obj else 0.0,
            "outreach_score": score_obj.outreach_score if score_obj else 0.0,
            "state": score_obj.state if score_obj else "RADAR",
        }

        # Recommendation
        recommendation = "Watch on Radar"
        if score_obj and score_obj.state == "HOT":
            if africa_label in ("A1_explicit_intent", "A2_active_regional_motion"):
                recommendation = f"Prepare Africa launch brief for {', '.join(countries) if countries else 'regional expansion'}"
            else:
                recommendation = "Human review; verify technical readiness & explore DevRel/Validator entry"
        elif score_obj and score_obj.state == "QUALIFIED":
            recommendation = "Review in morning digest queue; evaluate BD fit"

        # Evidence Items
        evidence_items = []
        for ev in evidence_list[:15]:
            evidence_items.append({
                "id": ev.id,
                "source_id": ev.source_id,
                "family": ev.source_family,
                "url": ev.url,
                "observed_at": ev.observed_at.isoformat() if ev.observed_at else None,
                "published_at": ev.published_at.isoformat() if ev.published_at else None,
                "claims": ev.extracted_claims,
            })

        card = {
            "header": {
                "candidate_id": chain.id,
                "canonical_name": chain.canonical_name,
                "organization": org_name,
                "official_domains": domains,
                "stage": chain.stage,
                "family": chain.stack_family,
                "stack_details": chain.stack_details,
                "layer": chain.layer,
                "discovered_at": chain.first_seen_at.isoformat() if chain.first_seen_at else None,
                "last_verified_at": chain.last_verified_at.isoformat() if chain.last_verified_at else None,
            },
            "why_now": {
                "recent_signals_count": len(evidence_list),
                "latest_event_time": evidence_list[0].observed_at.isoformat() if evidence_list else None,
                "highlight": f"New public signal detected from {evidence_list[0].source_id if evidence_list else 'registry'}",
            },
            "identity": {
                "caip2": caip2,
                "chain_id": chain_id,
                "genesis_fingerprint": genesis_fp,
                "environment": primary_net.environment if primary_net else "testnet",
                "parent_chain": chain.parent_chain,
                "da_layer": chain.da_layer,
                "rpc_urls": primary_net.rpc_urls if primary_net else [],
                "explorer_urls": primary_net.explorer_urls if primary_net else [],
            },
            "funding": {
                "total_disclosed_usd": total_funding_usd,
                "rounds_count": len(funding_list),
                "rounds": funding_list,
            },
            "timeline": {
                "repo_created_at": chain.repo_created_at.isoformat() if chain.repo_created_at else None,
                "registry_pr_opened_at": chain.registry_pr_opened_at.isoformat() if chain.registry_pr_opened_at else None,
                "registry_merged_at": chain.registry_merged_at.isoformat() if chain.registry_merged_at else None,
                "testnet_announced_at": chain.testnet_announced_at.isoformat() if chain.testnet_announced_at else None,
                "mainnet_announced_for": chain.mainnet_announced_for.isoformat() if chain.mainnet_announced_for else None,
                "mainnet_live_at": chain.mainnet_live_at.isoformat() if chain.mainnet_live_at else None,
            },
            "africa": {
                "label": africa_label,
                "score": africa_score,
                "countries": countries,
                "regions": regions,
                "confidence": africa.confidence if africa else 0.0,
                "sub_scores": {
                    "explicit_geo": africa.explicit_geo_score if africa else 0.0,
                    "regional_action": africa.regional_action_score if africa else 0.0,
                    "use_case_fit": africa.use_case_fit_score if africa else 0.0,
                    "whitespace": africa.whitespace_score if africa else 0.0,
                    "contactability": africa.contactability_score if africa else 0.0,
                    "operating_capacity": africa.operating_capacity_score if africa else 0.0,
                },
            },
            "opportunities": opp_list,
            "people_and_channels": contact_list,
            "scores": scores,
            "recommendation": recommendation,
            "evidence": evidence_items,
        }
        return card

    @classmethod
    def to_markdown(cls, card: Dict[str, Any]) -> str:
        """Converts an evidence card dictionary to readable GitHub-flavored Markdown."""
        h = card["header"]
        i = card["identity"]
        a = card["africa"]
        s = card["scores"]
        f = card.get("funding", {})
        
        funding_md = "No publicly announced funding recorded."
        if f.get("rounds"):
            f_rows = []
            for r in f["rounds"]:
                amt = r.get("amount_as_published") or "Undisclosed"
                lead = f" (Led by {r['lead_investor']})" if r.get("lead_investor") else ""
                f_rows.append(f"- **{r['round_type'].upper()}**: {amt}{lead} — [Source Link]({r['source_url']})\n  > \"{r.get('quote') or ''}\"")
            funding_md = "\n".join(f_rows)
        
        md = f"""# Evidence Card: {h['canonical_name']}

**Organization**: {h['organization']}  
**Stage**: `{h['stage']}` | **Family/Stack**: `{h['family']}` ({h.get('stack_details') or 'standard'}) | **Layer**: `{h['layer']}`  
**Discovered At**: {h['discovered_at']} | **Last Verified**: {h['last_verified_at'] or 'Unverified'}

---

### 1. Why Now
- **Latest Signal**: {card['why_now']['highlight']}
- **Total Evidence Count**: {card['why_now']['recent_signals_count']} events recorded

### 2. Technical Identity
- **CAIP-2**: `{i['caip2']}`
- **Chain ID**: `{i['chain_id'] or 'N/A'}`
- **Genesis Fingerprint**: `{i['genesis_fingerprint']}`
- **RPC Endpoints**: {', '.join(i['rpc_urls']) if i['rpc_urls'] else 'None'}
- **Explorers**: {', '.join(i['explorer_urls']) if i['explorer_urls'] else 'None'}

### 3. Africa Assessment
- **Classification**: **`{a['label']}`** (Confidence: {a['confidence'] * 100:.0f}%)
- **Africa Fit Score**: **{a['score']}/100**
- **Matched Countries**: {', '.join(a['countries']) if a['countries'] else 'None explicitly stated'}
- **Regions**: {', '.join(a['regions']) if a['regions'] else 'None'}

### 4. Funding & Disclosed Capital
{funding_md}

### 5. Scoring & Pipeline State
- **Confidence (C)**: `{s['confidence']}/100` | **Momentum (M)**: `{s['momentum']}/100`
- **Africa Fit (A)**: `{s['africa_fit']}/100` | **Risk (R)**: `{s['risk']}/100`
- **Radar Score**: `{s['radar_score']}/100`
- **Outreach Priority**: `{s['outreach_score']}/100`
- **Queue State**: **`{s['state']}`**

### 6. Recommended Next Action
> **{card['recommendation']}**

### 7. Primary Evidence Sources
"""
        for ev in card["evidence"][:5]:
            md += f"- [{ev['source_id']}]({ev['url']}) (Observed: {ev['observed_at']})\n"

        return md
