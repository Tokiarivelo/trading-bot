import { GenerateBotForm } from "@/features/strategies/GenerateBotForm";
import { StrategyDraftList } from "@/features/strategies/StrategyDraftList";
import { StrategyVersionList } from "@/features/strategies/StrategyVersionList";
import { SymbolAssignmentPanel } from "@/features/strategies/SymbolAssignmentPanel";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export const metadata = { title: "Bots — AI Trading Bot" };

export default function BotsPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <MenuButton />
        <h1 className="text-base font-bold">Bots</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <section>
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">
            Create a bot — generate with AI (prompt or PDF)
          </h2>
          <div className="p-4 pt-2">
            <GenerateBotForm />
          </div>
        </section>
        <section className="mt-2 border-t border-line">
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">
            Symbol assignments — which bot trades each symbol live
          </h2>
          <SymbolAssignmentPanel />
        </section>
        <section className="mt-2 border-t border-line">
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">Drafts pending review</h2>
          <StrategyDraftList showUploadForm={false} />
        </section>
        <section className="mt-2 border-t border-line">
          <h2 className="px-4 pt-3 text-sm font-semibold text-ink-muted">
            All bots — versions, manual/AI-prompt edit, archive, delete
          </h2>
          <StrategyVersionList />
        </section>
      </main>
    </div>
  );
}
