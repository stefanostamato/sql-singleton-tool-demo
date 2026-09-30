import { describe, expect, it } from "vitest";
import { argSummary } from "./summary";

const c = (name: string, input: unknown) => ({ name, input });

describe("argSummary", () => {
  it("shows a matter_id as #id", () => {
    expect(argSummary(c("docket_entries", { matter_id: 10001 }))).toBe("#10001");
  });
  it("shows the first participant and +k for more", () => {
    expect(argSummary(c("mail_search", { participants: ["a@x.com"] }))).toBe("a@x.com");
    expect(argSummary(c("mail_search", { participants: ["a@x.com", "b", "c"] }))).toBe("a@x.com +2");
  });
  it("shows after and before dates", () => {
    expect(argSummary(c("mail_search", { after: "2026-09-01", before: "2026-09-15" }))).toBe(
      "2026-09-01..2026-09-15",
    );
    expect(argSummary(c("time_entries", { after: "2026-09-01" }))).toBe("from 2026-09-01");
    expect(argSummary(c("mail_search", { before: "2026-09-15" }))).toBe("until 2026-09-15");
  });
  it("appends the page", () => {
    expect(argSummary(c("matters_list", { status: "Open", page: 2 }))).toBe("p2");
    expect(argSummary(c("time_entries", { after: "2026-09-01", page: 2 }))).toBe("from 2026-09-01 p2");
  });
  it("still understands the older matter field", () => {
    expect(argSummary(c("x", { matter: "HV-2026-0007" }))).toBe("#0007");
  });
  it("shows the first 40 characters of SQL with an ellipsis when cut", () => {
    const sql = "select * from matters m join docket_entries d using(matter_id) where 1=1";
    expect(argSummary(c("sql_query", { sql }))).toBe(sql.slice(0, 40).replace(/\s+/g, " ") + "...");
    expect(argSummary(c("sql_query", { sql: "select 1" }))).toBe("select 1");
  });
  it("collapses whitespace in SQL", () => {
    expect(argSummary(c("sql_query", { sql: "select\n  1\n from t" }))).toBe("select 1 from t");
  });
  it("is empty for no input", () => {
    expect(argSummary(c("describe_schema", {}))).toBe("");
    expect(argSummary(c("x", null))).toBe("");
  });
});
