export type ColumnKind = "number" | "date" | "text" | "boolean";

export interface ColumnProfile {
  name: string;
  kind: ColumnKind;
  dtype: string;
  null_count: number;
  distinct_count: number;
  min: string | null;
  max: string | null;
  examples: string[];
}

export interface TableProfile {
  name: string;
  display_name: string;
  rows: number;
  columns: ColumnProfile[];
  sample: Record<string, string | null>[];
  warnings: string[];
}

export interface JoinKey {
  column: string;
  tables: string[];
  overlap: number;
}

export interface WorkspaceSummary {
  tables: TableProfile[];
  joins: JoinKey[];
  model: string;
  messages?: Answer[];
  added?: string[];
}

export type ChartKind = "kpi" | "line" | "bar" | "scatter" | "table";

export interface ChartPayload {
  kind: ChartKind;
  x: string | null;
  x_label?: string | null;
  series: { key: string; name: string }[];
  data: Record<string, string | number | null>[];
  horizontal: boolean;
  kpis: { label: string; value: string }[];
  reason: string;
}

export interface Attempt {
  sql: string;
  error: string;
}

export interface Answer {
  question: string;
  title: string;
  narrative: string;
  explanation: string;
  sql: string | null;
  chart_hint: string;
  clarification: string | null;
  error: string | null;
  attempts: Attempt[];
  truncated: boolean;
  elapsed_ms: number;
  healed: boolean;
  ok: boolean;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  row_count: number;
  chart: ChartPayload | null;
}
