import { describe, expect, it } from "vitest";
import { fmtSeeds } from "./format";

describe("fmtSeeds", () => {
  it("uses the singular for one seed", () => expect(fmtSeeds([11])).toBe("seed 11"));
  it("joins two seeds with and", () => expect(fmtSeeds([11, 12])).toBe("seeds 11 and 12"));
  it("uses commas and a final and for more", () => expect(fmtSeeds([11, 12, 13])).toBe("seeds 11, 12 and 13"));
});
