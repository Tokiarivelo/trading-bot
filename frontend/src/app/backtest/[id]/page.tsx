import { BacktestReportDetail } from "@/features/backtest/BacktestReportDetail";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export default async function BacktestReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  // Next hands dynamic segments through still percent-encoded (verified via
  // Playwright — clicking the report list's Link produced a request with
  // `%20` re-encoded to `%2520`), so decode once here before it's used to
  // build any further request/link.
  const { id: rawId } = await params;
  const id = decodeURIComponent(rawId);
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <MenuButton />
        <span className="text-sm font-semibold text-ink-muted">Backtest Report</span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <BacktestReportDetail reportId={id} />
      </main>
    </div>
  );
}
