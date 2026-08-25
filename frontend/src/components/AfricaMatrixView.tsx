"use client";

import React, { useEffect, useState } from "react";
import { Globe, MapPin, DollarSign, Layers } from "lucide-react";

export const AfricaMatrixView: React.FC = () => {
  const [markets, setMarkets] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchMatrix = async () => {
      try {
        const res = await fetch("/api/analytics/africa_matrix");
        const data = await res.json();
        setMarkets(data.priority_markets || []);
      } catch (e) {
        console.error(e);
      } finally {
        setIsLoading(false);
      }
    };
    fetchMatrix();
  }, []);

  const priorityHubs = [
    { city: "Lagos", country: "Nigeria", region: "West Africa", currency: "NGN", rails: "Interswitch, Flutterwave, Paystack, MoMo" },
    { city: "Nairobi", country: "Kenya", region: "East Africa", currency: "KES", rails: "M-Pesa, Airtel Money, Chipper" },
    { city: "Accra", country: "Ghana", region: "West Africa", currency: "GHS", rails: "MTN Mobile Money, Vodafone Cash" },
    { city: "Cape Town", country: "South Africa", region: "Southern Africa", currency: "ZAR", rails: "EFT, Ozow, Luno" },
    { city: "Cairo", country: "Egypt", region: "North Africa", currency: "EGP", rails: "Fawry, Vodafone Cash, Meeza" },
    { city: "Kigali", country: "Rwanda", region: "East Africa", currency: "RWF", rails: "MTN MoMo, Airtel" },
    { city: "Dakar", country: "Senegal", region: "Francophone West", currency: "XOF", rails: "Orange Money, Wave" },
    { city: "Casablanca", country: "Morocco", region: "North Africa", currency: "MAD", rails: "Maroc Telecommerce, CMI" },
  ];

  const regionalBlocs = [
    { name: "AfCFTA", desc: "African Continental Free Trade Area (54 Member States)" },
    { name: "ECOWAS", desc: "Economic Community of West African States (Nigeria, Ghana, Senegal...)" },
    { name: "EAC", desc: "East African Community (Kenya, Tanzania, Uganda, Rwanda...)" },
    { name: "SADC", desc: "Southern African Development Community (South Africa, Angola...)" },
  ];

  return (
    <div className="space-y-8 animate-in fade-in duration-300">
      {/* Overview Banner */}
      <div className="glass-panel p-6 border-cyan-500/20 bg-gradient-to-r from-cyan-950/30 via-slate-900/50 to-purple-950/30">
        <div className="flex items-center space-x-3 mb-2">
          <Globe className="w-6 h-6 text-emerald-400" />
          <h2 className="text-xl font-extrabold text-white">Africa Market Matrix & Expansion Intelligence</h2>
        </div>
        <p className="text-xs text-slate-300 max-w-3xl leading-relaxed">
          The intelligence engine strictly differentiates <strong>A1 Explicit Intent</strong> (official roadmaps, local grants, country hiring) from <strong>A3 Inferred Fit</strong> (payment rails compatibility, low-fee architecture). 54 countries and regional economic blocs are tracked.
        </p>
      </div>

      {/* Priority Tech Hubs & Local Rails */}
      <div>
        <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
          <MapPin className="w-4 h-4 text-emerald-400" /> Priority African Tech Hubs & Settlement Rails
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {priorityHubs.map((hub) => (
            <div key={hub.city} className="glass-card p-4 border-white/5 space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-bold text-white">{hub.city}</h4>
                <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  {hub.country}
                </span>
              </div>
              <p className="text-[11px] text-slate-400">{hub.region}</p>
              <div className="pt-2 border-t border-white/5 text-[11px] space-y-1">
                <div className="flex items-center justify-between text-slate-400">
                  <span>Currency:</span>
                  <strong className="text-cyan-300 font-mono">{hub.currency}</strong>
                </div>
                <div className="text-[10px] text-slate-500 leading-tight">
                  Rails: {hub.rails}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Regional Blocs */}
      <div>
        <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400 mb-4 flex items-center gap-2">
          <Layers className="w-4 h-4 text-cyan-400" /> Regional Economic Blocs & Free Trade Frameworks
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {regionalBlocs.map((bloc) => (
            <div key={bloc.name} className="glass-card p-4 border-white/5 space-y-1.5">
              <h4 className="text-sm font-bold text-cyan-300">{bloc.name}</h4>
              <p className="text-[11px] text-slate-400 leading-normal">{bloc.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
