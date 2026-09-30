export type Arm = "tools" | "tools-lean" | "sql";
export type Variant = "base" | "math" | "textdeadlines";
export type Profile = "v1" | "v2";
export const VARIANTS: Variant[] = ["base", "math", "textdeadlines"];
export type Source = "matters" | "docket" | "mail" | "billing";
export const SOURCES: Source[] = ["matters", "docket", "mail", "billing"];

export interface Usage {
  input_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  output_tokens: number;
}

export interface ApiCall {
  source: Source;
  endpoint: string;
  params: Record<string, unknown>;
  started_ms: number;
  duration_ms: number;
  bytes: number;
}

export interface ToolCall {
  id: string;
  /** Time spent loading tables locally (sql_query only, when recorded). */
  load_ms?: number;
  name: string;
  input: unknown;
  is_error: boolean;
  duration_ms: number;
  result_bytes: number;
  result_tokens_est: number;
  preview: string;
  api_calls: ApiCall[];
}

export interface Turn {
  index: number;
  started_ms: number;
  model_ms: number;
  tools_ms: number;
  usage: Usage;
  context_tokens: number;
  cost_usd: number;
  stop_reason: string;
  /** Retries of the model call in this turn, when recorded. */
  retries?: number;
  /** Time spent waiting between those retries. */
  retry_wait_ms?: number;
  text: string;
  tool_calls: ToolCall[];
}

export type Outcome =
  | "answered"
  | "budget_stop"
  | "turn_limit"
  | "context_overflow"
  | "refusal"
  | "error"
  | "max_tokens";

export interface AtRisk {
  attorney: string;
  matters: string[];
}

export interface Totals extends Usage {
  turns: number;
  tool_calls: number;
  api_calls: number;
  context_peak_tokens: number;
  result_bytes: number;
  cost_usd: number;
  wall_ms: number;
  model_ms: number;
  tools_ms: number;
}

export interface TrapErrors {
  false_positives: string[];
  false_negatives: string[];
}

export interface Score {
  expected_count: number;
  submitted_count: number;
  precision: number;
  recall: number;
  f1: number;
  grouping_exact: boolean;
  false_positives: string[];
  false_negatives: string[];
  /** Phase 2: errors grouped by trap type; only kinds with at least one error are listed. */
  errors_by_trap?: Record<string, TrapErrors>;
}

export interface Trace {
  schema_version: number;
  run_id: string;
  arm: Arm;
  n_matters: number;
  rep: number;
  stage: string;
  pot: string;
  model: string;
  effort: string | null;
  latency_s: number;
  seed: number;
  variant?: Variant;
  profile?: Profile;
  today: string;
  started_at: string;
  finished_at: string;
  outcome: Outcome;
  error: string | null;
  question: string;
  system_prompt: string;
  tools: { name: string; description: string }[];
  turns: Turn[];
  answer: { at_risk: AtRisk[]; notes?: string } | null;
  totals: Totals;
  score: Score | null;
}

/** An index row as stored on disk. Phase 1 rows lack variant, profile and seed. */
export interface RawIndexRow extends Totals {
  run_id: string;
  stage: string;
  arm: Arm;
  n_matters: number;
  rep: number;
  model: string;
  outcome: Outcome;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  grouping_exact: boolean | null;
  variant?: Variant;
  profile?: Profile;
  seed?: number | null;
}

export interface IndexRow extends Totals {
  run_id: string;
  stage: string;
  arm: Arm;
  n_matters: number;
  rep: number;
  model: string;
  outcome: Outcome;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  grouping_exact: boolean | null;
  variant: Variant;
  profile: Profile;
  /** null for phase 1 rows, whose index does not record the seed. */
  seed: number | null;
}

export interface Truth {
  n_matters: number;
  seed: number;
  today: string;
  at_risk: AtRisk[];
  traps: Record<string, number>;
}

