const TONE: Record<string, string> = {
  pending_review: "border-ink-muted text-ink-muted",
  approved: "border-accent text-accent",
  rejected: "border-err text-err",
  code_generated: "border-ok text-ok",
  validated: "border-accent text-accent",
  active: "border-ok text-ok",
  archived: "border-ink-muted text-ink-muted",
  paused: "border-err text-err",
  // 10-trade refinement loop (Phase 7, F5)
  no_action: "border-ink-muted text-ink-muted",
  refinement_proposed: "border-accent text-accent",
  pending: "border-ink-muted text-ink-muted",
  backtested: "border-accent text-accent",
  applied: "border-ok text-ok",
  // News windows (Phase 8, F8)
  pre: "border-err text-err",
  post: "border-accent text-accent",
  low: "border-ink-muted text-ink-muted",
  medium: "border-accent text-accent",
  high: "border-err text-err",
  // Trade history outcome (F7 history view)
  win: "border-ok text-ok",
  loss: "border-err text-err",
  breakeven: "border-ink-muted text-ink-muted",
  open: "border-accent text-accent",
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
