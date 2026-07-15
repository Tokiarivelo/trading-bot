"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { GenerateBotForm } from "@/features/strategies/GenerateBotForm";
import { StrategyDraftList } from "@/features/strategies/StrategyDraftList";
import { StrategyVersionList } from "@/features/strategies/StrategyVersionList";
import { SymbolAssignmentPanel } from "@/features/strategies/SymbolAssignmentPanel";
import { MenuButton } from "@/shared/ui/NavigationDrawer";
import {
  getSkillAssignments,
  getStrategyDrafts,
  getStrategyVersions,
  getEngineStatus,
  type EngineStatus,
} from "@/shared/api/client";

export default function BotsPage() {
  const searchParams = useSearchParams();
  const initialTab = searchParams.get("tab") || "deployments";
  const [activeTab, setActiveTab] = useState<string>(initialTab);
  
  const [stats, setStats] = useState({
    activeBots: 0,
    liveSymbols: 0,
    pendingDrafts: 0,
    totalVersions: 0,
  });
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);

  const fetchStats = () => {
    setLoadingStats(true);
    Promise.all([
      getSkillAssignments(),
      getStrategyDrafts(),
      getStrategyVersions(),
      getEngineStatus(),
    ])
      .then(([skills, drafts, versions, eng]) => {
        const uniqueActive = new Set(
          versions.filter((v) => v.status === "active").map((v) => v.name)
        );
        setStats({
          activeBots: uniqueActive.size,
          liveSymbols: skills.length,
          pendingDrafts: drafts.filter((d) => d.status === "pending_review").length,
          totalVersions: versions.length,
        });
        setEngine(eng);
      })
      .catch((err) => {
        console.error("Failed to load page stats:", err);
      })
      .finally(() => {
        setLoadingStats(false);
      });
  };

  useEffect(() => {
    fetchStats();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Tabs structure
  const tabs = [
    {
      id: "deployments",
      label: "⚡ Live Deployments",
      description: "Map bot strategies to symbol instruments for live execution",
      component: <SymbolAssignmentPanel />,
    },
    {
      id: "ai_factory",
      label: "🔬 AI Bot Factory",
      description: "Generate new trading bots from natural language prompts or PDF specifications",
      component: <GenerateBotForm />,
    },
    {
      id: "library",
      label: "📁 Bot Library",
      description: "Manage, fork, rollback, or edit all generated strategy versions",
      component: <StrategyVersionList />,
    },
    {
      id: "drafts",
      label: "📥 Draft Inbox",
      description: "Review and generate code for pending AI draft strategies",
      component: <StrategyDraftList showUploadForm={false} />,
    },
  ];

  const currentTab = tabs.find((t) => t.id === activeTab) || tabs[0];

  return (
    <div className="flex h-screen flex-col bg-bg text-ink">
      {/* Header bar */}
      <header className="flex items-center gap-3 border-b border-line px-6 py-3 bg-panel/30 backdrop-blur-md">
        <MenuButton />
        <div className="flex flex-col">
          <h1 className="text-lg font-bold tracking-wide text-ink">Bots Hub</h1>
          <p className="text-3xs text-ink-muted uppercase tracking-wider font-semibold">
            Control Center & AI Generation
          </p>
        </div>
        <button
          onClick={fetchStats}
          title="Refresh Data"
          className="ml-auto cursor-pointer rounded-lg p-1.5 border border-line bg-panel hover:bg-bg text-ink-muted hover:text-ink transition-all duration-200"
        >
          <svg
            className={`w-4 h-4 ${loadingStats ? "animate-spin" : ""}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10H18.228"
            />
          </svg>
        </button>
      </header>

      {/* Main scrolling viewport */}
      <main className="min-h-0 flex-1 overflow-y-auto p-6 space-y-6">
        {/* Stats Grid */}
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Stat 1 */}
          <div className="rounded-xl border border-line bg-panel/60 p-4 shadow-sm backdrop-blur-md hover:border-line-hover transition-all duration-200 flex items-center gap-4">
            <div className="rounded-lg bg-accent/10 p-3 text-accent">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <span className="block text-2xs font-semibold text-ink-muted uppercase tracking-wider">Active Bots</span>
              <span className="block text-xl font-extrabold text-ink mt-0.5">{stats.activeBots}</span>
            </div>
          </div>

          {/* Stat 2 */}
          <div className="rounded-xl border border-line bg-panel/60 p-4 shadow-sm backdrop-blur-md hover:border-line-hover transition-all duration-200 flex items-center gap-4">
            <div className="rounded-lg bg-buy/10 p-3 text-buy">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <span className="block text-2xs font-semibold text-ink-muted uppercase tracking-wider">Live Feeds</span>
              <span className="block text-xl font-extrabold text-ink mt-0.5">{stats.liveSymbols}</span>
            </div>
          </div>

          {/* Stat 3 */}
          <div className="rounded-xl border border-line bg-panel/60 p-4 shadow-sm backdrop-blur-md hover:border-line-hover transition-all duration-200 flex items-center gap-4">
            <div className="rounded-lg bg-sell/10 p-3 text-sell">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <span className="block text-2xs font-semibold text-ink-muted uppercase tracking-wider">Pending Drafts</span>
              <span className="block text-xl font-extrabold text-ink mt-0.5">{stats.pendingDrafts}</span>
            </div>
          </div>

          {/* Stat 4 */}
          <div className="rounded-xl border border-line bg-panel/60 p-4 shadow-sm backdrop-blur-md hover:border-line-hover transition-all duration-200 flex items-center gap-4">
            <div className={`rounded-lg p-3 ${engine && !engine.paused ? "bg-ok/10 text-ok" : "bg-err/10 text-err"}`}>
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <span className="block text-2xs font-semibold text-ink-muted uppercase tracking-wider">Engine Status</span>
              <span className="flex items-center gap-1.5 mt-0.5">
                <span className={`h-2 w-2 rounded-full ${engine && !engine.paused ? "bg-ok animate-pulse" : "bg-err"}`} />
                <span className="text-sm font-bold text-ink uppercase tracking-wide">
                  {engine ? (engine.paused ? "Paused" : "Active") : "Loading..."}
                </span>
              </span>
            </div>
          </div>
        </section>

        {/* Tab Controls */}
        <section className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2 border-b border-line pb-2">
            {tabs.map((tab) => {
              const active = tab.id === activeTab;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={`cursor-pointer rounded-lg px-4 py-2.5 text-sm font-semibold tracking-wide transition-all duration-200 border ${
                    active
                      ? "bg-accent/15 border-accent text-accent shadow-sm"
                      : "border-transparent text-ink-muted hover:text-ink hover:bg-panel/40"
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Tab Content Header */}
          <div className="flex flex-col gap-1 px-1">
            <h2 className="text-base font-bold text-ink">{currentTab.label.split(" ").slice(1).join(" ")}</h2>
            <p className="text-xs text-ink-muted">{currentTab.description}</p>
          </div>

          {/* Tab Content Renderer */}
          <div className="rounded-xl border border-line bg-panel/30 shadow-inner overflow-hidden transition-all duration-300">
            {currentTab.component}
          </div>
        </section>
      </main>
    </div>
  );
}
