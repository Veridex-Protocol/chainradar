import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ChainRadar | Early Chain Discovery & Africa Expansion Intelligence",
  description: "Production-ready, evidence-first intelligence pipeline for discovering public blockchains, classifying Africa relevance, and generating actionable outreach briefs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark h-full antialiased">
      <body className="min-h-full bg-[#06090e] text-slate-100">{children}</body>
    </html>
  );
}
