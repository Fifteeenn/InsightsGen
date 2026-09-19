import { useState } from "react";
import { AlertCircle, ChevronDown, ChevronRight, Download, HelpCircle, Sparkles, Wrench } from "lucide-react";
import type { Answer } from "../types";
import { toCsv } from "../format";
import Chart from "./Chart";
import Kpis from "./Kpis";
import ResultTable from "./ResultTable";

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function AnswerCard({ a }: { a: Answer }) {
  const [open, setOpen] = useState(false);

  if (a.clarification) {
    return (
      <div className="card p-4 flex gap-3 rise" style={{ background: "var(--accent-soft)", borderColor: "transparent" }}>
        <HelpCircle size={18} style={{ color: "var(--accent-ink)", marginTop: 2, flexShrink: 0 }} />
        <div>
          <div className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--accent-ink)" }}>Quick check before I compute</div>
          <div className="mt-0.5">{a.clarification}</div>
        </div>
      </div>
    );
  }

  if (a.error) {
    return (
      <div className="card p-4 rise" style={{ borderColor: "var(--bad)" }}>
        <div className="flex gap-3">
          <AlertCircle size={18} style={{ color: "var(--bad)", marginTop: 2, flexShrink: 0 }} />
          <div className="min-w-0">
            <div className="font-medium">I could not answer that</div>
            <div className="text-sm mt-0.5" style={{ color: "var(--ink-2)" }}>{a.error}</div>
          </div>
        </div>
        {a.attempts.length > 0 && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer" style={{ color: "var(--muted)" }}>What was tried</summary>
            {a.attempts.map((t, i) => (
              <div key={i} className="mt-2">
                <div className="text-xs" style={{ color: "var(--bad)" }}>Attempt {i + 1}: {t.error}</div>
                <pre className="sql mt-1">{t.sql}</pre>
              </div>
            ))}
          </details>
        )}
      </div>
    );
  }

  const chart = a.chart;
  const badges: string[] = [];
  if (a.healed) badges.push(`self-corrected after ${a.attempts.length} failed attempt${a.attempts.length > 1 ? "s" : ""}`);
  if (a.truncated) badges.push("capped at 1,000 rows");

  return (
    <div className="card p-4 sm:p-5 rise">
      {a.title && <div className="font-semibold text-[15px] mb-1">{a.title}</div>}
      <p className="m-0 leading-relaxed">{a.narrative}</p>

      {chart && chart.kind === "kpi" && <div className="mt-4"><Kpis kpis={chart.kpis} /></div>}
      {chart && (chart.kind === "line" || chart.kind === "bar" || chart.kind === "scatter") && (
        <div className="mt-4 -ml-1"><Chart chart={chart} /></div>
      )}
      {chart && chart.kind === "table" && a.row_count > 0 && (
        <div className="mt-4"><ResultTable columns={a.columns} rows={a.rows} total={a.row_count} /></div>
      )}

      <button onClick={() => setOpen((o) => !o)} className="mt-4 flex items-center gap-1.5 text-sm bg-transparent border-0 p-0 cursor-pointer" style={{ color: "var(--ink-2)" }}>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>How I computed this</span>
        {badges.map((b) => (
          <span key={b} className="pill ml-1">{b.startsWith("self") ? <Wrench size={11} /> : null}{b}</span>
        ))}
      </button>

      {open && (
        <div className="mt-3 space-y-3 rise">
          {a.explanation && (
            <div className="flex gap-2 text-sm" style={{ color: "var(--ink-2)" }}>
              <Sparkles size={15} style={{ marginTop: 3, flexShrink: 0 }} />
              <span>{a.explanation}</span>
            </div>
          )}
          <pre className="sql">{a.sql}</pre>
          {chart && chart.kind !== "table" && <ResultTable columns={a.columns} rows={a.rows} total={a.row_count} />}
          {a.attempts.length > 0 && (
            <div className="text-sm">
              <div className="font-medium mb-1">Earlier attempts that failed</div>
              {a.attempts.map((t, i) => (
                <div key={i} className="mb-2">
                  <div className="text-xs" style={{ color: "var(--bad)" }}>Attempt {i + 1}: {t.error}</div>
                  <pre className="sql mt-1">{t.sql}</pre>
                </div>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <span className="text-xs" style={{ color: "var(--muted)" }}>
              {a.row_count.toLocaleString()} row{a.row_count === 1 ? "" : "s"} · {Math.round(a.elapsed_ms).toLocaleString()} ms end to end
            </span>
            <button className="btn" onClick={() => download("insightsgen_result.csv", toCsv(a.columns, a.rows))}>
              <Download size={14} /> Download CSV
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
