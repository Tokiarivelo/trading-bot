const TONE: Record<string, string> = {
  pending_review: "border-ink-muted text-ink-muted",
  approved: "border-accent text-accent",
  rejected: "border-err text-err",
  code_generated: "border-ok text-ok",
  validated: "border-accent text-accent",
  active: "border-ok text-ok",
  archived: "border-ink-muted text-ink-muted",
};

/** Small status pill shared by draft and version lists/detail pages. */
export function StatusBadge({ status }: { status: string }) {
  const cls = TONE[status] ?? "border-line text-ink-muted";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs whitespace-nowrap ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}
