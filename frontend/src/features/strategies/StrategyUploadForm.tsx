"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, uploadStrategyPdf } from "@/shared/api/client";

/** Upload a PDF describing a manual trading method; on success, jumps to the
 * new draft's review screen (§8.1 — nothing is ever activated automatically,
 * this only produces something for the user to review). */
export function StrategyUploadForm() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onUpload(form: FormData) {
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("choose a PDF file first");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const draft = await uploadStrategyPdf(file);
      router.push(`/strategies/drafts/${draft.id}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      action={onUpload}
      className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-panel p-3 text-sm"
    >
      <input
        className="flex-1 text-ink-muted file:mr-3 file:cursor-pointer file:rounded file:border file:border-line file:bg-bg file:px-2 file:py-1 file:text-ink"
        name="file"
        type="file"
        accept="application/pdf"
        required
      />
      <button
        className="cursor-pointer rounded border border-accent px-3 py-1 text-accent hover:bg-accent hover:text-bg disabled:opacity-50"
        disabled={busy}
        type="submit"
      >
        {busy ? "Extracting…" : "Upload PDF"}
      </button>
      {error && <p className="w-full text-err">{error}</p>}
    </form>
  );
}
