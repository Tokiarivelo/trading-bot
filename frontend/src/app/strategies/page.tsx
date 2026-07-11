import { StrategyDraftList } from "@/features/strategies/StrategyDraftList";
import { StrategyVersionList } from "@/features/strategies/StrategyVersionList";

export const metadata = { title: "Strategies — AI Trading Bot" };

export default function StrategiesPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="border-b border-line px-4 py-2">
        <h1 className="text-base font-bold">Strategies</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <section>
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">PDF drafts</h2>
          <StrategyDraftList />
        </section>
        <section className="mt-2 border-t border-line">
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">Versions</h2>
          <StrategyVersionList />
        </section>
      </main>
    </div>
  );
}
