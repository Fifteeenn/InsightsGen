const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtNumber(v: unknown, compact = false): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  const n = typeof v === "number" ? v : Number(v);
  if (Number.isNaN(n)) return String(v);
  if (compact) {
    const abs = Math.abs(n);
    if (abs >= 1e9) return `${(n / 1e9).toFixed(1).replace(/\.0$/, "")}B`;
    if (abs >= 1e6) return `${(n / 1e6).toFixed(1).replace(/\.0$/, "")}M`;
    if (abs >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, "")}K`;
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }
  return Number.isInteger(n)
    ? n.toLocaleString("en-US")
    : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function isNumeric(v: unknown): boolean {
  return typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)) && !/^\d{4}-\d{2}/.test(v));
}

const ISO = /^(\d{4})-(\d{2})(?:-(\d{2}))?/;

/** "2024-03-01" -> "Mar 2024" when every date is a month start, else "1 Mar 2024". */
export function dateFormatter(values: unknown[]): (v: unknown) => string {
  const strs = values.filter((v): v is string => typeof v === "string" && ISO.test(v));
  const monthly = strs.length > 0 && strs.every((s) => /^\d{4}-\d{2}(-01)?/.test(s));
  const yearly = strs.length > 0 && strs.every((s) => /^\d{4}-01-01/.test(s));
  return (v: unknown) => {
    if (typeof v !== "string") return String(v ?? "");
    const m = ISO.exec(v);
    if (!m) return v;
    const [, y, mo, d] = m;
    if (yearly) return y;
    if (monthly) return `${MONTHS[Number(mo) - 1]} ${y}`;
    return `${Number(d ?? 1)} ${MONTHS[Number(mo) - 1]} ${y}`;
  };
}

export function humanize(s: string): string {
  return s.replace(/[_\s]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()).trim();
}

export function toCsv(columns: string[], rows: unknown[][]): string {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))].join("\n");
}
