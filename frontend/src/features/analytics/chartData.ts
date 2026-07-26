/** `lightweight-charts` requires strictly ascending, unique timestamps per
 * series — but two trades can close within the same second, so
 * `equity_curve` (grouped by close_time) can carry duplicate times. Collapse
 * consecutive same-time points with `reduce` before calling `setData`. */
export function collapseByTime<T extends { time: number }>(
  points: T[],
  reduce: (accumulated: T, next: T) => T,
): T[] {
  const result: T[] = [];
  for (const p of points) {
    const last = result[result.length - 1];
    if (last && last.time === p.time) {
      result[result.length - 1] = reduce(last, p);
    } else {
      result.push(p);
    }
  }
  return result;
}
