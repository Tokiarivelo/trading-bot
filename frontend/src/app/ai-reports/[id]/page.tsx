import { AnalysisReportDetail } from "@/features/ai-reports/AnalysisReportDetail";

export default async function AnalysisReportPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        <AnalysisReportDetail reportId={id} />
      </main>
    </div>
  );
}
