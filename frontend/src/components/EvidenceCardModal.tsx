"use client";

import React, { useState } from "react";
import { DetailedCandidate } from "@/types";
import {
  X,
  ShieldCheck,
  Globe,
  Zap,
  Copy,
  ExternalLink,
  Edit3,
  Layers,
  Terminal,
  Activity,
  CheckCircle2,
  AlertTriangle,
  UserCheck,
} from "lucide-react";

interface EvidenceCardModalProps {
  candidateId: string;
  candidateData: DetailedCandidate | null;
  isLoading: boolean;
  onClose: () => void;
  onRefresh: () => void;
}

export const EvidenceCardModal: React.FC<EvidenceCardModalProps> = ({
  candidateId,
  candidateData,
  isLoading,
  onClose,
  onRefresh,
}) => {
  const [activeTab, setActiveTab] = useState<"summary" | "tech" | "africa" | "scoring" | "opps" | "provenance">("summary");
  const [isVerifying, setIsVerifying] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!candidateData && isLoading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
        <div className="p-8 rounded-2xl bg-slate-900 border border-slate-800 text-center">
          <Activity className="w-8 h-8 text-cyan-400 animate-spin mx-auto mb-3" />
          <p className="text-sm font-semibold text-slate-300">Loading Evidence Card...</p>
        </div>
      </div>
    );
  }

  if (!candidateData) return null;

  const c = candidateData;

  const handleVerifyRpc = async () => {
    setIsVerifying(true);
    try {
      const res = await fetch(`/api/candidates/${candidateId}/verify`, { method: "POST" });
      const data = await res.json();
      alert(`Probe completed! Checked ${data.probes?.length || 0} endpoint(s).`);
      onRefresh();
    } catch (e: any) {
      alert(`Verification probe error: ${e.message}`);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleOverrideAfrica = async () => {
    const newLabel = prompt("Enter new Africa label (A1_explicit_intent, A2_active_regional_motion, A3_africa_compatible, A4_no_evidence):", c.africa.label);
    if (!newLabel) return;
    const reason = prompt("Enter rationale for analyst override:", "Verified official Nigeria/Kenya expansion documentation");
    if (!reason) return;

    try {
      const res = await fetch(`/api/candidates/${candidateId}/override_africa`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent_label: newLabel, reason, actor: "analyst" }),
      });
      if (res.ok) {
        alert("Africa label override saved successfully!");
        onRefresh();
      }
    } catch (e: any) {
      alert(`Failed to save override: ${e.message}`);
    }
  };

  const handleCopyMarkdown = async () => {
    try {
      const res = await fetch(`/api/candidates/${candidateId}/evidence_card?format=markdown`);
      const data = await res.json();
      navigator.clipboard.writeText(data.markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (e: any) {
      alert(`Failed to copy markdown: ${e.message}`);
    }
  };

  const handleWorkflowTransition = async (newState: string) => {
    try {
      const res = await fetch(`/api/candidates/${candidateId}/transition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow_state: newState, actor: "analyst", reason: "Analyst dashboard update" }),
      });
      if (res.ok) {
        alert(`Workflow state updated to ${newState}`);
        onRefresh();
      }
    } catch (e: any) {
      alert(`Failed to update workflow: ${e.message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md overflow-y-auto">
      <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-4xl shadow-2xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="p-6 border-b border-white/10 flex items-center justify-between bg-slate-950/60">
          <div>
            <div className="flex items-center space-x-3">
              <h2 className="text-xl font-extrabold text-white tracking-tight">
                {c.header.canonical_name}
              </h2>
              <span className="px-2.5 py-0.5 text-xs font-bold rounded-full bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                {c.header.stage.replace(/_/g, " ").toUpperCase()}
              </span>
              <span className={`px-2.5 py-0.5 text-xs font-bold rounded-full border ${
                c.scores.state === "HOT" ? "bg-rose-500/20 text-rose-300 border-rose-500/40" : "bg-slate-800 text-slate-300 border-slate-700"
              }`}>
                {c.scores.state}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1">
              Organization: <strong className="text-slate-200">{c.header.organization}</strong> • Official Domains: {c.header.official_domains.join(", ") || "None"}
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={handleCopyMarkdown}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-400 border border-slate-700 transition-colors flex items-center gap-1.5 text-xs font-medium"
              title="Copy Markdown Card"
            >
              <Copy className="w-3.5 h-3.5" />
              <span>{copied ? "Copied!" : "Copy MD"}</span>
            </button>

            <button
              onClick={onClose}
              className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Tab Bar */}
        <div className="flex border-b border-white/5 bg-slate-950/40 px-6 overflow-x-auto custom-scrollbar">
          {[
            { id: "summary", label: "Executive Brief" },
            { id: "tech", label: "Technical & RPC" },
            { id: "africa", label: "Africa Market Fit" },
            { id: "scoring", label: "Scoring Radar" },
            { id: "opps", label: "Opportunities & Contacts" },
            { id: "provenance", label: "Evidence Ledger" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`py-3 px-4 text-xs font-semibold border-b-2 whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? "border-cyan-400 text-cyan-300 bg-cyan-500/5"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto custom-scrollbar flex-1 space-y-6">
          {activeTab === "summary" && (
            <div className="space-y-6">
              <div className="p-4 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                <h4 className="text-xs font-bold uppercase text-cyan-400 tracking-wider mb-1 flex items-center gap-1.5">
                  <Zap className="w-4 h-4" /> Why Now & Discovery Summary
                </h4>
                <p className="text-sm text-slate-200 leading-relaxed font-medium">
                  {c.why_now.highlight}
                </p>
                <div className="mt-3 flex items-center gap-4 text-xs text-slate-400">
                  <span>Signals Observed: <strong className="text-cyan-300">{c.why_now.recent_signals_count}</strong></span>
                  <span>Lifecycle: <strong className="text-slate-200">{c.why_now.lifecycle_summary}</strong></span>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider mb-2">
                  Recommended Action & Strategy
                </h4>
                <p className="text-sm text-slate-300 leading-relaxed">
                  {c.recommendation}
                </p>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                  <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider mb-1">Outreach Priority</h4>
                  <span className="text-2xl font-black text-rose-400">{c.scores.outreach_score}/100</span>
                  <p className="text-xs text-slate-500 mt-1">Calculated based on confidence, Africa fit, and momentum.</p>
                </div>
                <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                  <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider mb-1">Africa Score</h4>
                  <span className="text-2xl font-black text-emerald-400">{c.africa.score}/100</span>
                  <p className="text-xs text-slate-500 mt-1">Classification: {c.africa.label}</p>
                </div>
              </div>
            </div>
          )}

          {activeTab === "tech" && (
            <div className="space-y-6">
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
                <h4 className="text-xs font-bold uppercase text-cyan-400 tracking-wider flex items-center gap-1.5">
                  <Layers className="w-4 h-4" /> Technical Fingerprint
                </h4>
                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <span className="text-slate-500 block">CAIP-2 Identifier:</span>
                    <code className="text-cyan-300 font-mono text-xs">{c.identity.caip2 || "N/A"}</code>
                  </div>
                  <div>
                    <span className="text-slate-500 block">Chain ID:</span>
                    <code className="text-slate-200 font-mono text-xs">{c.identity.chain_id || "N/A"}</code>
                  </div>
                  <div className="col-span-2">
                    <span className="text-slate-500 block">Genesis Fingerprint:</span>
                    <code className="text-slate-400 font-mono text-[11px] break-all">{c.identity.genesis_fingerprint}</code>
                  </div>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider">
                    Published RPC Endpoints
                  </h4>
                  <button
                    onClick={handleVerifyRpc}
                    disabled={isVerifying || c.identity.rpc_urls.length === 0}
                    className="px-3 py-1.5 rounded-lg bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-xs font-bold flex items-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>{isVerifying ? "Probing..." : "Run Safe Probe"}</span>
                  </button>
                </div>

                {c.identity.rpc_urls.length > 0 ? (
                  <div className="space-y-1.5">
                    {c.identity.rpc_urls.map((rpc, idx) => (
                      <div key={idx} className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-xs text-slate-300 flex items-center justify-between">
                        <span className="truncate">{rpc}</span>
                        <span className="text-[10px] text-emerald-400 px-2 py-0.5 rounded bg-emerald-500/10">SSRF Checked</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic">No public RPC endpoints published yet.</p>
                )}
              </div>
            </div>
          )}

          {activeTab === "africa" && (
            <div className="space-y-6">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-bold uppercase text-emerald-400 tracking-wider">
                    Classification: {c.africa.label}
                  </h4>
                  <p className="text-xs text-slate-300 mt-1">
                    Confidence: <strong>{(c.africa.confidence * 100).toFixed(0)}%</strong> • Total Score: <strong>{c.africa.score}/100</strong>
                  </p>
                </div>
                <button
                  onClick={handleOverrideAfrica}
                  className="px-3 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-500/40 text-xs font-bold flex items-center gap-1.5"
                >
                  <Edit3 className="w-3.5 h-3.5" />
                  <span>Override Label</span>
                </button>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Explicit Geo</span>
                  <span className="block text-lg font-black text-emerald-400">{c.africa.sub_scores.explicit_geo}/30</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Regional Action</span>
                  <span className="block text-lg font-black text-teal-400">{c.africa.sub_scores.regional_action}/20</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Use Case Fit</span>
                  <span className="block text-lg font-black text-cyan-400">{c.africa.sub_scores.use_case_fit}/15</span>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
                <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider">Matched Countries & Regions</h4>
                <div className="flex flex-wrap gap-1.5">
                  {c.africa.countries.length > 0 ? (
                    c.africa.countries.map((ct) => (
                      <span key={ct} className="px-2.5 py-1 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 text-xs font-bold">
                        {ct}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-slate-500">None explicitly named</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === "scoring" && (
            <div className="space-y-4">
              <div className="grid grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Confidence (C)</span>
                  <span className="block text-xl font-black text-purple-400">{c.scores.confidence}/100</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Momentum (M)</span>
                  <span className="block text-xl font-black text-cyan-400">{c.scores.momentum}/100</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Africa Fit (A)</span>
                  <span className="block text-xl font-black text-emerald-400">{c.scores.africa_fit ?? c.africa.score}/100</span>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/60 border border-slate-800 text-center">
                  <span className="text-[10px] text-slate-500 uppercase font-black">Risk (R)</span>
                  <span className="block text-xl font-black text-rose-400">{c.scores.risk}/100</span>
                </div>
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider mb-2">Workflow State Transition</h4>
                <div className="flex items-center gap-2">
                  <select
                    defaultValue={c.scores.workflow_state || "NEW"}
                    onChange={(e) => handleWorkflowTransition(e.target.value)}
                    className="bg-slate-900 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-slate-200"
                  >
                    <option value="NEW">NEW - Uncontacted</option>
                    <option value="QUALIFIED">QUALIFIED - Pre-Screened</option>
                    <option value="CONTACTED">CONTACTED - Outreach Sent</option>
                    <option value="CONVERSATION">IN CONVERSATION</option>
                    <option value="ACTIVE_PARTNER">ACTIVE PARTNER</option>
                    <option value="REJECTED">REJECTED / ARCHIVED</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {activeTab === "opps" && (
            <div className="space-y-6">
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
                <h4 className="text-xs font-bold uppercase text-cyan-400 tracking-wider">
                  Extracted Opportunities & Grants
                </h4>
                {c.opportunities.length > 0 ? (
                  <div className="space-y-2">
                    {c.opportunities.map((op, idx) => (
                      <div key={idx} className="p-3 rounded bg-slate-900 border border-slate-800 text-xs">
                        <span className="font-bold text-slate-200 uppercase">{op.type.replace(/_/g, " ")}: </span>
                        <span className="text-slate-300">{op.summary}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic">No specific grants or hackathons extracted yet.</p>
                )}
              </div>

              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
                <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider flex items-center gap-1.5">
                  <UserCheck className="w-4 h-4 text-emerald-400" /> Public Business Contacts (NDPA Compliant)
                </h4>
                {c.people_and_channels.length > 0 ? (
                  <div className="space-y-2">
                    {c.people_and_channels.map((ct, idx) => (
                      <div key={idx} className="p-3 rounded bg-slate-900 border border-slate-800 text-xs flex items-center justify-between">
                        <div>
                          <strong className="text-slate-200">{ct.role}</strong> ({ct.channel_type}):{" "}
                          <code className="text-cyan-300 font-mono">{ct.value}</code>
                        </div>
                        <span className="text-[10px] text-slate-500">Purpose: {ct.permitted_purpose}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 italic">No public contacts recorded.</p>
                )}
              </div>
            </div>
          )}

          {activeTab === "provenance" && (
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-3">
              <h4 className="text-xs font-bold uppercase text-slate-400 tracking-wider">
                Origin Evidence Events & Provenance Ledger
              </h4>
              <div className="space-y-2">
                {c.evidence.map((ev) => (
                  <div key={ev.id} className="p-2.5 rounded bg-slate-900 border border-slate-800 text-xs flex items-center justify-between">
                    <div className="flex items-center space-x-2 truncate">
                      <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-slate-800 text-cyan-300">
                        {ev.source_id}
                      </span>
                      <a
                        href={ev.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-300 hover:text-cyan-400 truncate flex items-center gap-1"
                      >
                        <span className="truncate">{ev.url}</span>
                        <ExternalLink className="w-3 h-3 flex-shrink-0" />
                      </a>
                    </div>
                    <span className="text-[10px] text-slate-500 font-mono whitespace-nowrap">
                      {new Date(ev.observed_at).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
