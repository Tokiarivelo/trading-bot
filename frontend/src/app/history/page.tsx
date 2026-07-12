import { TradeHistoryList } from "@/features/history/TradeHistoryList";

export const metadata = { title: "Trade history — AI Trading Bot" };

export default function TradeHistoryPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="border-b border-line px-4 py-2">
        <h1 className="text-base font-bold">Trade history</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <TradeHistoryList />
      </main>
    </div>
  );
}
