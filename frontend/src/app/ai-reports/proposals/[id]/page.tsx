import { RefinementProposalDetail } from "@/features/ai-reports/RefinementProposalDetail";

export default async function RefinementProposalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div className="flex h-screen flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        <RefinementProposalDetail proposalId={id} />
      </main>
    </div>
  );
}
