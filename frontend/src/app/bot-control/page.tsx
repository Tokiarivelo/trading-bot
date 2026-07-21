"use client";

import { BotsBySymbolPanel } from "@/features/bot-control/BotsBySymbolPanel";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export default function BotControlPage() {
  return (
    <div className="flex h-screen flex-col bg-bg text-ink">
      <header className="flex items-center gap-3 border-b border-line px-6 py-3 bg-panel/30 backdrop-blur-md">
        <MenuButton />
        <div className="flex flex-col">
          <h1 className="text-lg font-bold tracking-wide text-ink">Bot Control</h1>
          <p className="text-3xs text-ink-muted uppercase tracking-wider font-semibold">
            Running bots by symbol — stop and flatten
          </p>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-6">
        <BotsBySymbolPanel />
      </main>
    </div>
  );
}
