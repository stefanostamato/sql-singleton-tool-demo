import { describe, expect, it } from "vitest";
import { normalizeRow, truthName } from "./normalize";
import { row } from "./testrows";
import type { RawIndexRow } from "./types";

const { variant: _v, profile: _p, seed: _s, ...old } = row();

describe("normalizeRow", () => {
  it("fills phase 1 defaults for a row without the new fields", () => {
    const n = normalizeRow(old as RawIndexRow);
    expect(n.variant).toBe("base");
    expect(n.profile).toBe("v1");
    expect(n.seed).toBeNull();
  });
  it("keeps values that are present", () => {
    const n = normalizeRow({ ...old, variant: "math", profile: "v2", seed: 11, arm: "tools-lean" } as RawIndexRow);
    expect([n.variant, n.profile, n.seed, n.arm]).toEqual(["math", "v2", 11, "tools-lean"]);
  });
  it("treats null fields like missing ones", () => {
    const n = normalizeRow({ ...old, variant: null, profile: null } as unknown as RawIndexRow);
    expect([n.variant, n.profile]).toEqual(["base", "v1"]);
  });
  it("falls back to base for a variant this build does not know", () => {
    expect(normalizeRow({ ...old, variant: "weird" } as unknown as RawIndexRow).variant).toBe("base");
  });
});

describe("truthName", () => {
  it("keeps the phase 1 file name for base v1 rows", () => {
    expect(truthName(row({ n_matters: 120 }))).toBe("n120");
  });
  it("uses the phase 2 file name otherwise", () => {
    expect(truthName(row({ variant: "math", profile: "v2", seed: 11, n_matters: 40 }))).toBe("math-v2-s11-n40");
  });
});
