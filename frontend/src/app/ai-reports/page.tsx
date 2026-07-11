import { AnalysisReportList } from "@/features/ai-reports/AnalysisReportList";

export const metadata = { title: "AI Reports — AI Trading Bot" };

export default function AiReportsPage() {
  return (
    <div className="flex h-screen flex-col">
      <header className="border-b border-line px-4 py-2">
        <h1 className="text-base font-bold">AI 10-trade reviews</h1>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <AnalysisReportList />
      </main>
    </div>
  );
}
