"use client";

import React, { useEffect, useState, useMemo } from "react";
import { Header } from "@/components/Header";
import { FunnelOverview } from "@/components/FunnelOverview";
import { CandidateCard } from "@/components/CandidateCard";
import { EvidenceCardModal } from "@/components/EvidenceCardModal";
import { AfricaMatrixView } from "@/components/AfricaMatrixView";
import { VerifierPlayground } from "@/components/VerifierPlayground";
import { SourceRegisterView } from "@/components/SourceRegisterView";
import { DigestCenter } from "@/components/DigestCenter";
import { TerminalDaemonGuide } from "@/components/TerminalDaemonGuide";
import { Candidate, DetailedCandidate } from "@/types";
import { Activity, Flame, Target, Radio, Globe, Layers, Filter } from "lucide-react";

export default function Home() {
  const [activeTab, setActiveTab] = useState<string>("hot");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedStack, setSelectedStack] = useState<string>("");
  const [selectedAfrica, setSelectedAfrica] = useState<string>("");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [selectedCandidateData, setSelectedCandidateData] = useState<DetailedCandidate | null>(null);
  const [isModalLoading, setIsModalLoading] = useState<boolean>(false);

  // Fetch candidates from FastAPI backend
  const fetchCandidates = async () => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("q", searchQuery);
      if (selectedStack) params.append("stack_family", selectedStack);
      if (selectedAfrica) params.append("africa_intent", selectedAfrica);

      const res = await fetch(`/api/candidates?${params.toString()}`);
      const data = await res.json();
      setCandidates(data.items || []);
    } catch (e) {
      console.error("Failed to fetch candidates:", e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchCandidates();
  }, [selectedStack, selectedAfrica]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchCandidates();
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Open Evidence Card Modal
  const handleOpenModal = async (candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setIsModalLoading(true);
    try {
      const res = await fetch(`/api/candidates/${candidateId}`);
      const data = await res.json();
      setSelectedCandidateData(data.candidate);
    } catch (e) {
      console.error("Failed to load candidate details:", e);
    } finally {
      setIsModalLoading(false);
    }
  };

  // Funnel counts
  const hotCandidates = useMemo(() => candidates.filter((c) => c.scores.state === "HOT"), [candidates]);
  const qualCandidates = useMemo(() => candidates.filter((c) => c.scores.state === "QUALIFIED"), [candidates]);
  const radarCandidates = useMemo(() => candidates.filter((c) => c.scores.state === "RADAR" || c.scores.state === "STALE"), [candidates]);
  const africaCandidates = useMemo(
    () => candidates.filter((c) => c.africa_label === "A1_explicit_intent" || c.africa_label === "A2_active_regional_motion"),
    [candidates]
  );

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top Navigation */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        searchQuery={searchQuery}
        setSearchQuery={setSearchQuery}
        selectedStack={selectedStack}
        setSelectedStack={setSelectedStack}
        selectedAfrica={selectedAfrica}
        setSelectedAfrica={setSelectedAfrica}
        onRefresh={fetchCandidates}
        isLoading={isLoading}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* KPI Funnel Overview (Shown on queue tabs) */}
        {["hot", "qualified", "radar"].includes(activeTab) && (
          <FunnelOverview
            hotCount={hotCandidates.length}
            qualifiedCount={qualCandidates.length}
            radarCount={radarCandidates.length}
            africaCount={africaCandidates.length}
            onSelectTab={setActiveTab}
          />
        )}

        {/* Tab 1: HOT Priority Alerts */}
        {activeTab === "hot" && (
          <div className="space-y-4 animate-in fade-in duration-300">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Flame className="w-5 h-5 text-rose-500" /> HOT Outreach Queue
                </h3>
                <p className="text-xs text-slate-400">
                  Qualified candidates passing all gates (Confidence ≥65, Momentum ≥40, Africa Fit ≥50, SSRF-verified RPC).
                </p>
              </div>
              <span className="text-xs font-bold text-rose-400 px-3 py-1 rounded-full bg-rose-500/10 border border-rose-500/30">
                {hotCandidates.length} Candidates Ready
              </span>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-20">
                <Activity className="w-8 h-8 text-cyan-400 animate-spin" />
              </div>
            ) : hotCandidates.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {hotCandidates.map((c) => (
                  <CandidateCard key={c.id} candidate={c} onOpenModal={handleOpenModal} />
                ))}
              </div>
            ) : (
              <div className="glass-card p-12 text-center text-slate-500 border-white/5 space-y-2">
                <p className="text-sm font-semibold">No candidates currently in HOT status.</p>
                <p className="text-xs">Run a live scan or browse the Qualified / Radar queues to evaluate candidates.</p>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Qualified Leads */}
        {activeTab === "qualified" && (
          <div className="space-y-4 animate-in fade-in duration-300">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Target className="w-5 h-5 text-amber-400" /> Qualified Pre-Mainnet Leads
                </h3>
                <p className="text-xs text-slate-400">
                  Public testnets and devnets with strong architectural backing and active ecosystem motions.
                </p>
              </div>
              <span className="text-xs font-bold text-amber-400 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/30">
                {qualCandidates.length} Leads
              </span>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-20">
                <Activity className="w-8 h-8 text-cyan-400 animate-spin" />
              </div>
            ) : qualCandidates.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {qualCandidates.map((c) => (
                  <CandidateCard key={c.id} candidate={c} onOpenModal={handleOpenModal} />
                ))}
              </div>
            ) : (
              <div className="glass-card p-12 text-center text-slate-500 border-white/5">
                <p className="text-sm font-semibold">No qualified candidates matching current filters.</p>
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Radar Watchlist */}
        {activeTab === "radar" && (
          <div className="space-y-4 animate-in fade-in duration-300">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center gap-2">
                  <Radio className="w-5 h-5 text-cyan-400" /> Radar Watchlist & Discovery Feed
                </h3>
                <p className="text-xs text-slate-400">
                  Continuous stream of registry PRs, code artifacts, and early testnet announcements.
                </p>
              </div>
              <span className="text-xs font-bold text-cyan-400 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30">
                {radarCandidates.length} Observed
              </span>
            </div>

            {isLoading ? (
              <div className="flex justify-center py-20">
                <Activity className="w-8 h-8 text-cyan-400 animate-spin" />
              </div>
            ) : radarCandidates.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {radarCandidates.map((c) => (
                  <CandidateCard key={c.id} candidate={c} onOpenModal={handleOpenModal} />
                ))}
              </div>
            ) : (
              <div className="glass-card p-12 text-center text-slate-500 border-white/5">
                <p className="text-sm font-semibold">No radar candidates matching current search criteria.</p>
              </div>
            )}
          </div>
        )}

        {/* Tab 4: Africa Matrix */}
        {activeTab === "africa" && <AfricaMatrixView />}

        {/* Tab 5: RPC Verifier */}
        {activeTab === "verifier" && <VerifierPlayground />}

        {/* Tab 6: Source Register */}
        {activeTab === "sources" && <SourceRegisterView />}

        {/* Tab 7: Digests & Reports */}
        {activeTab === "digests" && <DigestCenter />}

        {/* Tab 8: Terminal & Daemon */}
        {activeTab === "terminal" && <TerminalDaemonGuide />}
      </main>

      {/* Evidence Card Modal */}
      {selectedCandidateId && (
        <EvidenceCardModal
          candidateId={selectedCandidateId}
          candidateData={selectedCandidateData}
          isLoading={isModalLoading}
          onClose={() => {
            setSelectedCandidateId(null);
            setSelectedCandidateData(null);
          }}
          onRefresh={() => {
            if (selectedCandidateId) handleOpenModal(selectedCandidateId);
            fetchCandidates();
          }}
        />
      )}
    </div>
  );
}
