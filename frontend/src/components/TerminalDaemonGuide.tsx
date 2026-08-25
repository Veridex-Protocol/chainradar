"use client";

import React, { useState } from "react";
import { Terminal, Play, Copy, Check, Shield, FileText } from "lucide-react";

export const TerminalDaemonGuide: React.FC = () => {
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null);

  const copyToClipboard = (cmd: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(cmd);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  const cliCommands = [
    {
      title: "1. Background Daemon & Automated Reporting",
      desc: "Runs continuous discovery polling in the background and writes scheduled 07:30 & 18:00 WAT intelligence reports to ./reports/digests/.",
      cmd: "chainradar daemon --interval 10 --reports",
    },
    {
      title: "2. Live Full-Screen Terminal TUI",
      desc: "Interactive live terminal dashboard with active pipeline queues, Africa expansion tickers, and collector health status.",
      cmd: "chainradar tui",
    },
    {
      title: "3. On-Demand Daily Report Generation",
      desc: "Generates instant Morning or Evening Intelligence Digest and exports Markdown & JSON briefs to disk.",
      cmd: "chainradar report generate --type morning --save",
    },
    {
      title: "4. Candidate Dataset CSV / JSON Export",
      desc: "Exports all active discovery candidates and Africa classifications to a spreadsheet CSV report.",
      cmd: "chainradar report export --format csv",
    },
    {
      title: "5. SSRF-Hardened Terminal RPC Probe",
      desc: "Performs instant safe RPC probe on any endpoint with pre-connect DNS validation and block 0 genesis checks.",
      cmd: "chainradar verify https://rpc.ankr.com/eth --family evm",
    },
    {
      title: "6. Real Live Collector Scan",
      desc: "Runs live discovery across Ethereum Lists, Superchain Registry, Cosmos Registry, and RSS feeds.",
      cmd: "chainradar scan --source all",
    },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="glass-panel p-6 border-cyan-500/20 bg-gradient-to-r from-slate-900 via-slate-900/60 to-cyan-950/20">
        <div className="flex items-center space-x-3 mb-2">
          <Terminal className="w-6 h-6 text-cyan-400" />
          <h2 className="text-xl font-extrabold text-white">Terminal CLI & Background Daemon Interface</h2>
        </div>
        <p className="text-xs text-slate-300 max-w-3xl leading-relaxed">
          ChainRadar features a native terminal CLI (<code>chainradar</code>) that can run as a background service daemon, interactive TUI, or scheduled report generator.
        </p>
      </div>

      {/* Commands Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {cliCommands.map((item) => (
          <div key={item.title} className="glass-card p-5 border-white/5 space-y-3 flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-slate-100 mb-1">{item.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{item.desc}</p>
            </div>

            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-xs text-cyan-300">
              <span className="truncate mr-2">$ {item.cmd}</span>
              <button
                onClick={() => copyToClipboard(item.cmd)}
                className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-colors flex-shrink-0"
                title="Copy Command"
              >
                {copiedCmd === item.cmd ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
