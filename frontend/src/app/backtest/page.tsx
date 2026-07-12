import { BacktestReportList } from "@/features/backtest/BacktestReportList";
import { MenuButton } from "@/shared/ui/NavigationDrawer";

export const metadata = { title: "Backtest reports — AI Trading Bot" };

export default function BacktestReportsPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2">
        <MenuButton />
        <h1 className="text-base font-bold">Backtest reports</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <BacktestReportList />
      </main>
    </div>
  );
}
