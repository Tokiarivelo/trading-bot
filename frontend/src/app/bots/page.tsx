"use client";

// `/bots` itself has no content of its own — it defers to the default tab.
// Preserves the query string so old links like `/bots?symbol=EURUSD` still
// carry the symbol through to /bots/deployments.
import { redirect, useSearchParams } from "next/navigation";

export default function BotsRootPage() {
  const searchParams = useSearchParams();
  const qs = searchParams.toString();
  redirect(qs ? `/bots/deployments?${qs}` : "/bots/deployments");
}
