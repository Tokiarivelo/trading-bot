import { StrategyDraftDetail } from "@/features/strategies/StrategyDraftDetail";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export default async function StrategyDraftPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <MenuButton />
        <span className="text-sm font-semibold text-ink-muted">Strategy Draft</span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <StrategyDraftDetail draftId={id} />
      </main>
    </div>
  );
}
