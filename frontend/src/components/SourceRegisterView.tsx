"use client";

import React, { useEffect, useState } from "react";
import { Source } from "@/types";
import { Settings, RefreshCw, Power, ShieldAlert, CheckCircle2 } from "lucide-react";

export const SourceRegisterView: React.FC = () => {
  const [sources, setSources] = useState<Source[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [syncingId, setSyncingId] = useState<string | null>(null);

  const fetchSources = async () => {
    try {
      const res = await fetch("/api/sources");
      const data = await res.json();
      setSources(data.sources || []);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchSources();
  }, []);

  const handleToggleKillSwitch = async (sourceId: string, currentState: boolean) => {
    try {
      const res = await fetch(`/api/sources/${sourceId}/toggle_kill_switch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disabled: !currentState, reason: "Operator UI toggle", actor: "analyst" }),
      });
      if (res.ok) {
        fetchSources();
      }
    } catch (e: any) {
      alert(`Kill switch toggle failed: ${e.message}`);
    }
  };

  const handleTriggerSync = async (sourceId: string) => {
    setSyncingId(sourceId);
    try {
      const res = await fetch(`/api/sources/${sourceId}/trigger_sync`, { method: "POST" });
      const data = await res.json();
      alert(`Sync finished for ${sourceId}. Processed ${data.processed_items} items.`);
      fetchSources();
    } catch (e: any) {
      alert(`Sync failed: ${e.message}`);
    } finally {
      setSyncingId(null);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="glass-panel p-6 border-cyan-500/20 bg-gradient-to-r from-slate-900 via-slate-900/60 to-purple-950/20">
        <div className="flex items-center space-x-3 mb-2">
          <Settings className="w-6 h-6 text-purple-400" />
          <h2 className="text-xl font-extrabold text-white">Source Register & Governance Health</h2>
        </div>
        <p className="text-xs text-slate-300 max-w-3xl leading-relaxed">
          Active data sources operate under strict rate budgets, conditional HTTP requests (ETag / If-None-Match), and zero private community crawling. Any collector can be disabled instantly via kill switch without pipeline disruption.
        </p>
      </div>

      {/* Sources Table */}
      <div className="glass-card overflow-hidden border-white/5">
        <div className="overflow-x-auto custom-scrollbar">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-950/80 border-b border-white/5 text-slate-400 font-bold uppercase tracking-wider">
              <tr>
                <th className="p-4">Source ID & Name</th>
                <th className="p-4">Family</th>
                <th className="p-4">Tier</th>
                <th className="p-4">Reliability</th>
                <th className="p-4">Cadence</th>
                <th className="p-4">Status</th>
                <th className="p-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {sources.map((s) => {
                const isSyncing = syncingId === s.source_id;
                return (
                  <tr key={s.source_id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="p-4 font-bold text-slate-200">
                      <div>{s.source_id}</div>
                      <div className="text-[11px] font-normal text-slate-500">{s.name}</div>
                    </td>
                    <td className="p-4 text-slate-400 uppercase font-mono text-[11px]">{s.family}</td>
                    <td className="p-4">
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700 font-bold">
                        Tier {s.tier}
                      </span>
                    </td>
                    <td className="p-4 font-mono font-bold text-cyan-300">{(s.reliability * 100).toFixed(0)}%</td>
                    <td className="p-4 text-slate-400 font-mono">{s.cadence}</td>
                    <td className="p-4">
                      {s.kill_switch ? (
                        <span className="px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-500/40 text-[10px] font-bold">
                          DISABLED
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 text-[10px] font-bold">
                          ACTIVE
                        </span>
                      )}
                    </td>
                    <td className="p-4 text-right space-x-2">
                      <button
                        onClick={() => handleTriggerSync(s.source_id)}
                        disabled={isSyncing || s.kill_switch}
                        className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] font-bold border border-slate-700 transition-colors disabled:opacity-40"
                      >
                        {isSyncing ? "Syncing..." : "Sync"}
                      </button>
                      <button
                        onClick={() => handleToggleKillSwitch(s.source_id, s.kill_switch)}
                        className={`px-2.5 py-1 rounded text-[11px] font-bold border transition-colors ${
                          s.kill_switch
                            ? "bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border-emerald-500/40"
                            : "bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border-rose-500/40"
                        }`}
                      >
                        {s.kill_switch ? "Enable" : "Kill"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
