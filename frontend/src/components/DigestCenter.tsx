"use client";

import React, { useState } from "react";
import { FileText, Copy, Download, Sparkles, Activity } from "lucide-react";

export const DigestCenter: React.FC = () => {
  const [digestType, setDigestType] = useState<"morning" | "evening">("morning");
  const [content, setContent] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async (type: "morning" | "evening") => {
    setDigestType(type);
    setIsLoading(true);
    try {
      const res = await fetch(`/api/digests/preview?type=${type}&format=markdown`);
      const data = await res.json();
      setContent(data.markdown);
    } catch (e: any) {
      setContent(`Failed to generate digest: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = () => {
    if (!content) return;
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    if (!content) return;
    const blob = new Blob([content], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chainradar_digest_${digestType}_${new Date().toISOString().split("T")[0]}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="glass-panel p-6 border-cyan-500/20 bg-gradient-to-r from-slate-900 via-slate-900/60 to-cyan-950/20">
        <div className="flex items-center space-x-3 mb-2">
          <FileText className="w-6 h-6 text-cyan-400" />
          <h2 className="text-xl font-extrabold text-white">Daily Intelligence Digests & Executive Reports</h2>
        </div>
        <p className="text-xs text-slate-300 max-w-3xl leading-relaxed">
          Automated briefs delivered at <strong>07:30 WAT</strong> (morning kickoff) and <strong>18:00 WAT</strong> (evening wrap). Compiles newly promoted HOT candidates, qualified testnets, testnet resets, and active Africa developer hiring signals.
        </p>
      </div>

      {/* Generation Bar */}
      <div className="glass-card p-4 border-white/5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          <button
            onClick={() => handleGenerate("morning")}
            disabled={isLoading}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
              digestType === "morning" && content
                ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20"
                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>07:30 WAT Morning Digest</span>
          </button>

          <button
            onClick={() => handleGenerate("evening")}
            disabled={isLoading}
            className={`px-4 py-2 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
              digestType === "evening" && content
                ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/20"
                : "bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700"
            }`}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>18:00 WAT Evening Digest</span>
          </button>
        </div>

        {content && (
          <div className="flex items-center space-x-2">
            <button
              onClick={handleCopy}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              <Copy className="w-3.5 h-3.5" />
              <span>{copied ? "Copied!" : "Copy Markdown"}</span>
            </button>
            <button
              onClick={handleDownload}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-xs font-medium flex items-center gap-1.5 transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download .md</span>
            </button>
          </div>
        )}
      </div>

      {/* Content Preview */}
      <div className="glass-card p-6 border-white/5 font-mono text-xs text-slate-300 min-h-[360px] bg-slate-950/80">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-500 space-y-2">
            <Activity className="w-6 h-6 text-cyan-400 animate-spin" />
            <span>Generating {digestType.toUpperCase()} intelligence brief...</span>
          </div>
        ) : content ? (
          <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-slate-200 custom-scrollbar overflow-x-auto">
            {content}
          </pre>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-slate-500 space-y-2">
            <FileText className="w-8 h-8 text-slate-600" />
            <span>Select a digest schedule above to generate and preview formatted brief.</span>
          </div>
        )}
      </div>
    </div>
  );
};
