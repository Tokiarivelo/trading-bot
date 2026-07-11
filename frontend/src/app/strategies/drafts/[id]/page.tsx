import { StrategyDraftDetail } from "@/features/strategies/StrategyDraftDetail";

export default async function StrategyDraftPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        <StrategyDraftDetail draftId={id} />
      </main>
    </div>
  );
}
