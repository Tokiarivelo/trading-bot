import { StrategyVersionDetail } from "@/features/strategies/StrategyVersionDetail";

export default async function StrategyVersionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        <StrategyVersionDetail versionId={id} />
      </main>
    </div>
  );
}
