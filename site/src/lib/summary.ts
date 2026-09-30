/** A short label for the arguments of a tool call, shown on the replay chips. */
export function argSummary(c: { name: string; input: unknown }): string {
  const i = c.input;
  if (!i || typeof i !== "object") return "";
  const a = i as Record<string, unknown>;
  if (typeof a.sql === "string") {
    const flat = a.sql.replace(/\s+/g, " ").trim();
    return flat.length > 40 ? flat.slice(0, 40).trimEnd() + "..." : flat;
  }
  const parts: string[] = [];
  if (typeof a.matter_id === "number" || typeof a.matter_id === "string") parts.push(`#${a.matter_id}`);
  else if (typeof a.matter === "string") parts.push(a.matter.replace("HV-2026-", "#"));
  if (Array.isArray(a.participants) && a.participants.length > 0) {
    const more = a.participants.length - 1;
    parts.push(String(a.participants[0]) + (more > 0 ? ` +${more}` : ""));
  }
  if (typeof a.after === "string" && typeof a.before === "string") parts.push(`${a.after}..${a.before}`);
  else if (typeof a.after === "string") parts.push(`from ${a.after}`);
  else if (typeof a.before === "string") parts.push(`until ${a.before}`);
  if (typeof a.page === "number") parts.push(`p${a.page}`);
  return parts.join(" ");
}
