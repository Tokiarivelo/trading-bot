/**
 * Helper utility to trigger a browser download of JSON data.
 */
export function downloadJson(data: unknown, filename: string): void {
  try {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    downloadBlob(blob, filename);
  } catch (err) {
    console.error("Failed to download JSON:", err);
  }
}

/**
 * Helper utility to trigger a browser download of tabular data as CSV.
 * Column set is the union of keys across all rows (rows need not be
 * uniform), in first-seen order, so callers can pass loosely-shaped data.
 */
export function downloadCsv(rows: Record<string, unknown>[], filename: string): void {
  try {
    if (rows.length === 0) {
      console.error("Failed to download CSV: no rows to export");
      return;
    }
    const headers: string[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
      for (const key of Object.keys(row)) {
        if (!seen.has(key)) {
          seen.add(key);
          headers.push(key);
        }
      }
    }
    const escape = (value: unknown): string => {
      if (value === null || value === undefined) return "";
      const str = typeof value === "string" ? value : JSON.stringify(value);
      return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
    };
    const lines = [
      headers.join(","),
      ...rows.map((row) => headers.map((h) => escape(row[h])).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
    downloadBlob(blob, filename);
  } catch (err) {
    console.error("Failed to download CSV:", err);
  }
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
