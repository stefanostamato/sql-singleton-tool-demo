import type { Arm, Outcome, Source, Variant } from "./lib/types";

export const REPO_URL = "https://github.com/stefanostamato/sql-singleton-tool-demo";
export const WRITEUP_URL = REPO_URL + "/blob/main/WRITEUP.md";

export const ARM_NAME: Record<Arm, string> = {
  tools: "Tool per system",
  "tools-lean": "Trimmed tools",
  sql: "SQL singleton",
};

export const SYSTEM_NAME: Record<Source, string> = {
  matters: "Matters",
  docket: "Court docket",
  mail: "Email",
  billing: "Billing",
};

export const OUTCOME_LABEL: Record<Outcome, string> = {
  answered: "Answered",
  budget_stop: "Stopped at budget",
  turn_limit: "Stopped at turn limit",
  context_overflow: "Context overflow",
  refusal: "Refused",
  error: "Error",
  max_tokens: "Hit the output limit",
};

/** Label for an outcome, tolerating values this build does not know yet. */
export const outcomeLabel = (o: string): string => (OUTCOME_LABEL as Record<string, string>)[o] ?? o;

export const VARIANT_NAME: Record<Variant, string> = {
  base: "Base task",
  math: "Math",
  textdeadlines: "Text deadlines",
};

/** "claude-sonnet-5-5" becomes "Sonnet 5.5"; unknown names pass through. */
export function modelLabel(model: string): string {
  const m = /^claude-([a-z]+)-(\d+)-(\d+)$/.exec(model);
  return m ? `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}.${m[3]}` : model;
}
