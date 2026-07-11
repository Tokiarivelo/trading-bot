import { BacktestReportDetail } from "@/features/backtest/BacktestReportDetail";

export default async function BacktestReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        <BacktestReportDetail reportId={id} />
      </main>
    </div>
  );
}
