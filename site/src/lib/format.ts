export function fmtTokens(n: number): string {
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e4) return Math.round(n / 1e3) + "k";
  return Math.round(n).toLocaleString("en-US");
}
export const fmtInt = (n: number) => Math.round(n).toLocaleString("en-US");
export const fmtSeconds = (ms: number) => (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + " s";
export const fmtCost = (usd: number) => "$" + usd.toFixed(usd >= 1 ? 2 : 3);
export const fmtRatio = (r: number | null) =>
  r === null ? "n/a" : (r >= 10 ? r.toFixed(0) : r.toFixed(1)) + "×";
export function fmtSeeds(seeds: number[]): string {
  const s = seeds.map(String);
  if (s.length <= 1) return `seed ${s[0] ?? ""}`.trim();
  return `seeds ${s.slice(0, -1).join(", ")} and ${s[s.length - 1]}`;
}
export const fmtPct = (x: number | null) => (x === null ? "–" : x.toFixed(2));
