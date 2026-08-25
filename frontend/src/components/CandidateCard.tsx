"use client";

import React from "react";
import { Candidate } from "@/types";
import { Zap, ShieldCheck, Globe, Layers, ArrowRight, Activity } from "lucide-react";

interface CandidateCardProps {
  candidate: Candidate;
  onOpenModal: (id: string) => void;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({ candidate, onOpenModal }) => {
  const isHot = candidate.scores.state === "HOT";
  const isQual = candidate.scores.state === "QUALIFIED";

  // Africa Label formatting
  const aLabel = candidate.africa_label || "A4_no_evidence";
  let aBadgeClass = "bg-slate-800 text-slate-400 border-slate-700";
  let aBadgeText = aLabel.replace(/_/g, " ");

  if (aLabel.startsWith("A1")) {
    aBadgeClass = "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";
    aBadgeText = "A1: Explicit Intent";
  } else if (aLabel.startsWith("A2")) {
    aBadgeClass = "bg-teal-500/20 text-teal-300 border-teal-500/40";
    aBadgeText = "A2: Regional Motion";
  } else if (aLabel.startsWith("A3")) {
    aBadgeClass = "bg-blue-500/20 text-blue-300 border-blue-500/40";
    aBadgeText = "A3: Compatible";
  }

  // Stage formatting
  let stageLabel = candidate.stage.replace(/_/g, " ").toUpperCase();
  if (stageLabel.startsWith("S2")) stageLabel = "S2: Public Testnet";
  if (stageLabel.startsWith("S1")) stageLabel = "S1: Devnet / Prototype";
  if (stageLabel.startsWith("S5")) stageLabel = "S5: Early Mainnet";

  return (
    <div
      onClick={() => onOpenModal(candidate.id)}
      className={`glass-card p-5 cursor-pointer border flex flex-col justify-between group relative overflow-hidden transition-all duration-300 ${
        isHot
          ? "border-rose-500/40 hover:border-rose-500/80 shadow-lg shadow-rose-500/5"
          : isQual
          ? "border-amber-500/30 hover:border-amber-500/60"
          : "border-white/5 hover:border-cyan-500/40"
      }`}
    >
      {/* Glow highlight for HOT */}
      {isHot && (
        <div className="absolute top-0 right-0 w-32 h-32 bg-rose-500/10 rounded-full blur-2xl -mr-16 -mt-16 pointer-events-none" />
      )}

      <div>
        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-3">
          <div>
            <h4 className="text-base font-bold text-slate-100 group-hover:text-cyan-300 transition-colors flex items-center gap-1.5">
              {candidate.name}
            </h4>
            <p className="text-xs text-slate-400 font-medium truncate max-w-[200px]">
              {candidate.organization || "Public Network Entity"}
            </p>
          </div>

          <span className="px-2 py-0.5 text-[10px] font-bold rounded-md bg-slate-900/90 text-slate-300 border border-slate-800 whitespace-nowrap">
            {stageLabel}
          </span>
        </div>

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 mb-4">
          <span className="px-2 py-0.5 text-[10px] font-bold rounded-md bg-indigo-500/15 text-indigo-300 border border-indigo-500/30 flex items-center gap-1">
            <Layers className="w-3 h-3" />
            {candidate.stack_family.toUpperCase()} ({candidate.layer || "L2"})
          </span>

          <span className={`px-2 py-0.5 text-[10px] font-bold rounded-md border flex items-center gap-1 ${aBadgeClass}`}>
            <Globe className="w-3 h-3" />
            {aBadgeText} ({candidate.africa_score})
          </span>

          {candidate.last_verified_at && (
            <span className="px-2 py-0.5 text-[10px] font-bold rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 flex items-center gap-1">
              <ShieldCheck className="w-3 h-3 text-emerald-400" />
              Verified RPC
            </span>
          )}
        </div>
      </div>

      {/* Scores Bar */}
      <div>
        <div className="grid grid-cols-3 gap-2 py-2.5 px-3 rounded-lg bg-slate-950/70 border border-slate-800/80 mb-3 text-center">
          <div>
            <span className="block text-[9px] uppercase font-black text-slate-500 tracking-wider">Outreach</span>
            <span className={`text-sm font-black ${isHot ? "text-rose-400" : isQual ? "text-amber-400" : "text-slate-300"}`}>
              {candidate.scores.outreach_score.toFixed(0)}
            </span>
          </div>
          <div className="border-x border-slate-800">
            <span className="block text-[9px] uppercase font-black text-slate-500 tracking-wider">Radar</span>
            <span className="text-sm font-black text-cyan-400">
              {candidate.scores.radar_score.toFixed(0)}
            </span>
          </div>
          <div>
            <span className="block text-[9px] uppercase font-black text-slate-500 tracking-wider">Confidence</span>
            <span className="text-sm font-black text-purple-400">
              {candidate.scores.confidence.toFixed(0)}%
            </span>
          </div>
        </div>

        {/* Footer Action */}
        <div className="flex items-center justify-between text-xs font-semibold text-slate-400 group-hover:text-cyan-400 transition-colors pt-1">
          <span>View Evidence Card</span>
          <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
        </div>
      </div>
    </div>
  );
};
