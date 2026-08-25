"use client";

import React from "react";
import { Flame, Target, Radio, Globe, ArrowUpRight } from "lucide-react";

interface FunnelOverviewProps {
  hotCount: number;
  qualifiedCount: number;
  radarCount: number;
  africaCount: number;
  onSelectTab: (tab: string) => void;
}

export const FunnelOverview: React.FC<FunnelOverviewProps> = ({
  hotCount,
  qualifiedCount,
  radarCount,
  africaCount,
  onSelectTab,
}) => {
  const cards = [
    {
      title: "HOT Alerts",
      subtitle: "Immediate Outreach Priority",
      count: hotCount,
      icon: Flame,
      tab: "hot",
      borderColor: "border-rose-500/30 hover:border-rose-500/60",
      bgGradient: "from-rose-500/10 via-rose-500/5 to-transparent",
      accentColor: "text-rose-400",
      pillBg: "bg-rose-500/20 text-rose-300 border-rose-500/40",
      description: "Gate passed (C≥65, M≥40, AfricaFit≥50, Verified RPC)",
    },
    {
      title: "Qualified Leads",
      subtitle: "Pre-Mainnet & Testnet Cohorts",
      count: qualifiedCount,
      icon: Target,
      tab: "qualified",
      borderColor: "border-amber-500/30 hover:border-amber-500/60",
      bgGradient: "from-amber-500/10 via-amber-500/5 to-transparent",
      accentColor: "text-amber-400",
      pillBg: "bg-amber-500/20 text-amber-300 border-amber-500/40",
      description: "Validated candidates with active roadmap & grant initiatives",
    },
    {
      title: "Radar Watchlist",
      subtitle: "Devnets & Early PRs",
      count: radarCount,
      icon: Radio,
      tab: "radar",
      borderColor: "border-cyan-500/30 hover:border-cyan-500/60",
      bgGradient: "from-cyan-500/10 via-cyan-500/5 to-transparent",
      accentColor: "text-cyan-400",
      pillBg: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
      description: "Registry additions, sliding GitHub PRs, and RaaS deployments",
    },
    {
      title: "Africa Intent",
      subtitle: "Explicit Intent & Regional Fit",
      count: africaCount,
      icon: Globe,
      tab: "africa",
      borderColor: "border-emerald-500/30 hover:border-emerald-500/60",
      bgGradient: "from-emerald-500/10 via-emerald-500/5 to-transparent",
      accentColor: "text-emerald-400",
      pillBg: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
      description: "A1/A2 verified across Nigeria, Kenya, Ghana, Egypt, & regional hubs",
    },
  ];

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
      {cards.map((c) => {
        const Icon = c.icon;
        return (
          <div
            key={c.title}
            onClick={() => onSelectTab(c.tab)}
            className={`glass-card p-5 cursor-pointer border bg-gradient-to-b ${c.bgGradient} ${c.borderColor} group relative overflow-hidden`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center space-x-2.5">
                <div className={`p-2 rounded-lg bg-slate-900/90 border border-white/5 ${c.accentColor}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-slate-100 group-hover:text-white transition-colors">
                    {c.title}
                  </h3>
                  <p className="text-[11px] text-slate-400">{c.subtitle}</p>
                </div>
              </div>
              <ArrowUpRight className="w-4 h-4 text-slate-500 group-hover:text-slate-200 transition-colors" />
            </div>

            <div className="flex items-baseline space-x-3 my-2">
              <span className={`text-3xl font-black tracking-tight ${c.accentColor}`}>
                {c.count}
              </span>
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${c.pillBg}`}>
                Active Queue
              </span>
            </div>

            <p className="text-[11px] text-slate-400 mt-2 line-clamp-1">
              {c.description}
            </p>
          </div>
        );
      })}
    </div>
  );
};
