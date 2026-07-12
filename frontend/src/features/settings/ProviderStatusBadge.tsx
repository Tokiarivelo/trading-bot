/** Green/red dot + label reflecting whether a provider is usable right now
 * (has its required secret/URL set), without ever showing the secret itself. */
export function ProviderStatusBadge({ configured }: { configured: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
      <span className={`h-2 w-2 rounded-full ${configured ? "bg-ok" : "bg-err"}`} aria-hidden />
      <span className={configured ? "text-ok" : "text-err"}>
        {configured ? "Configured" : "Not configured"}
      </span>
    </span>
  );
}
