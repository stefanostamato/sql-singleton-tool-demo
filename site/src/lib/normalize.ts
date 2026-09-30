import { VARIANTS, type IndexRow, type Profile, type RawIndexRow, type Variant } from "./types";

/** The one place that defaults fields missing from older rows (phase 1). */
export function normalizeRow(r: RawIndexRow): IndexRow {
  const variant: Variant = VARIANTS.includes(r.variant as Variant) ? (r.variant as Variant) : "base";
  const profile: Profile = r.profile === "v2" ? "v2" : "v1";
  return { ...r, variant, profile, seed: typeof r.seed === "number" ? r.seed : null };
}

/** File name (without .json) of the ground truth for a run. */
export function truthName(r: Pick<IndexRow, "variant" | "profile" | "seed" | "n_matters">): string {
  if (r.variant === "base" && r.profile === "v1") return `n${r.n_matters}`;
  return `${r.variant}-${r.profile}-s${r.seed}-n${r.n_matters}`;
}
