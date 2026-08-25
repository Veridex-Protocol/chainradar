"use client";

import React, { useEffect, useState } from "react";
import { Activity, Clock, RefreshCw, Terminal, Search, ShieldAlert, Sparkles } from "lucide-react";

interface HeaderProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  selectedStack: string;
  setSelectedStack: (stack: string) => void;
  selectedAfrica: string;
  setSelectedAfrica: (a: string) => void;
  selectedFunding?: string;
  setSelectedFunding?: (f: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  searchQuery,
  setSearchQuery,
  selectedStack,
  setSelectedStack,
  selectedAfrica,
  setSelectedAfrica,
  selectedFunding = "",
  setSelectedFunding,
  onRefresh,
  isLoading,
}) => {
  const [watTime, setWatTime] = useState<string>("");

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const utc = now.getTime() + now.getTimezoneOffset() * 60000;
      const wat = new Date(utc + 3600000 * 1);
      setWatTime(wat.toTimeString().split(" ")[0]);
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const navItems = [
    { id: "hot", label: "HOT Alerts", badge: "🔥 Priority" },
    { id: "qualified", label: "Qualified Leads", badge: "🎯 Pre-Mainnet" },
    { id: "radar", label: "Radar Watchlist", badge: "📡 Devnets" },
    { id: "africa", label: "Africa Matrix", badge: "🌍 54 Markets" },
    { id: "verifier", label: "RPC Verifier", badge: "⚡ Safe Probe" },
    { id: "sources", label: "Source Register", badge: "⚙️ Health" },
    { id: "digests", label: "Digests & Reports", badge: "📑 Briefs" },
    { id: "terminal", label: "Terminal & Daemon", badge: "💻 CLI" },
  ];

  return (
    <header className="border-b border-white/10 bg-slate-950/80 backdrop-blur-xl sticky top-0 z-40">
      {/* Top Banner */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 via-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="text-xl font-extrabold tracking-tight bg-gradient-to-r from-cyan-400 via-sky-300 to-purple-400 bg-clip-text text-transparent">
                  ChainRadar
                </span>
                <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                  v1.0.0
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Early Chain Discovery & Africa Expansion Intelligence Engine
              </p>
            </div>
          </div>

          {/* Center Search & Filters */}
          <div className="hidden md:flex items-center space-x-3 flex-1 max-w-md mx-6">
            <div className="relative w-full">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Search chains, domains, CAIP-2, chainId..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-slate-900/90 border border-slate-800 rounded-lg pl-9 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-colors"
              />
            </div>

            <select
              value={selectedStack}
              onChange={(e) => setSelectedStack(e.target.value)}
              className="bg-slate-900/90 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
            >
              <option value="">All Stacks</option>
              <option value="evm">EVM</option>
              <option value="cosmos">Cosmos / CometBFT</option>
              <option value="substrate">Substrate</option>
              <option value="svm">Solana / SVM</option>
              <option value="starknet">Starknet</option>
              <option value="fuel">FuelVM</option>
              <option value="aptos">Aptos Move</option>
              <option value="sui">Sui Move</option>
            </select>

            <select
              value={selectedAfrica}
              onChange={(e) => setSelectedAfrica(e.target.value)}
              className="bg-slate-900/90 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
            >
              <option value="">All Africa Intent</option>
              <option value="A1_explicit_intent">A1: Explicit Intent</option>
              <option value="A2_active_regional_motion">A2: Regional Motion</option>
              <option value="A3_africa_compatible">A3: Compatible</option>
              <option value="A4_no_evidence">A4: No Evidence</option>
            </select>

            {setSelectedFunding && (
              <select
                value={selectedFunding}
                onChange={(e) => setSelectedFunding(e.target.value)}
                className="bg-slate-900/90 border border-slate-800 rounded-lg px-2.5 py-1.5 text-xs text-amber-300 focus:outline-none focus:border-amber-500"
              >
                <option value="">All Capital</option>
                <option value="recent">⚡ Recent Funding (Q3 2025–Now)</option>
                <option value="funded">💰 All Funded</option>
                <option value="unfunded">🔍 Unfunded / Bootstrapped</option>
              </select>
            )}
          </div>

          {/* Right Status */}
          <div className="flex items-center space-x-4">
            {/* WAT Clock */}
            <div className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800">
              <Clock className="w-3.5 h-3.5 text-cyan-400" />
              <span className="text-xs font-mono font-bold text-slate-200">{watTime || "--:--:--"}</span>
              <span className="text-[10px] text-slate-400">WAT</span>
            </div>

            {/* Refresh Button */}
            <button
              onClick={onRefresh}
              disabled={isLoading}
              className="p-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 hover:text-cyan-400 transition-colors"
              title="Refresh Pipeline"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin text-cyan-400" : ""}`} />
            </button>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex space-x-1 overflow-x-auto py-2 custom-scrollbar border-t border-white/5">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id)}
                className={`flex items-center space-x-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all whitespace-nowrap ${
                  isActive
                    ? "bg-cyan-500/15 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-500/20"
                    : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
                }`}
              >
                <span>{item.label}</span>
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded-md ${
                    isActive ? "bg-cyan-500/30 text-cyan-200" : "bg-slate-800/80 text-slate-400"
                  }`}
                >
                  {item.badge}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </header>
  );
};
