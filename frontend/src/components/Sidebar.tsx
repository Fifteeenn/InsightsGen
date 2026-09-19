import { useRef, useState } from "react";
import { BarChart3, ChevronDown, ChevronRight, Database, Link2, Moon, Sun, Trash2, Upload, X } from "lucide-react";
import type { TableProfile, WorkspaceSummary } from "../types";

interface Props {
  summary: WorkspaceSummary | null;
  busy: boolean;
  onUpload: (files: File[]) => void;
  onSample: () => void;
  onRemove: (name: string) => void;
  onClear: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onClose?: () => void;
}

function TableCard({ t, onRemove }: { t: TableProfile; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center gap-2 px-3 py-2.5 bg-transparent border-0 cursor-pointer text-left" style={{ color: "var(--ink)" }}>
        {open ? <ChevronDown size={15} style={{ color: "var(--muted)" }} /> : <ChevronRight size={15} style={{ color: "var(--muted)" }} />}
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-medium truncate">{t.display_name}</div>
          <div className="text-xs" style={{ color: "var(--muted)" }}>{t.rows.toLocaleString()} rows · {t.columns.length} columns · <span className="mono">{t.name}</span></div>
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-1.5 rise">
          {t.columns.map((c) => (
            <div key={c.name} className="text-xs flex gap-2 items-baseline">
              <span className="pill" style={{ minWidth: 52, justifyContent: "center" }}>{c.kind}</span>
              <span className="mono" style={{ color: "var(--ink)" }}>{c.name}</span>
              <span className="truncate" style={{ color: "var(--muted)" }}>
                {c.kind === "number" || c.kind === "date" ? (c.min !== null ? `${c.min} → ${c.max}` : "") : c.examples.slice(0, 2).join(", ")}
                {c.null_count > 0 ? ` · ${c.null_count} nulls` : ""}
              </span>
            </div>
          ))}
          {t.warnings.map((w) => (
            <div key={w} className="text-xs flex gap-2 items-start pt-1">
              <span className="pill pill-warn">cleaned</span>
              <span style={{ color: "var(--ink-2)" }}>{w}</span>
            </div>
          ))}
          <button className="btn mt-2" style={{ fontSize: 12, padding: "4px 9px" }} onClick={onRemove}>
            <Trash2 size={12} /> Remove table
          </button>
        </div>
      )}
    </div>
  );
}

export default function Sidebar({ summary, busy, onUpload, onSample, onRemove, onClear, theme, onToggleTheme, onClose }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const tables = summary?.tables ?? [];
  const joins = summary?.joins ?? [];

  const handleFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    onUpload(Array.from(list));
    if (input.current) input.current.value = "";
  };

  return (
    <aside className="h-full min-h-0 flex flex-col" style={{ background: "var(--surface)", borderRight: "1px solid var(--border)" }}>
      <div className="px-4 pt-4 pb-3 flex items-center gap-2.5">
        <div className="rounded-lg flex items-center justify-center" style={{ width: 32, height: 32, background: "var(--accent)" }}>
          <BarChart3 size={18} color="#fff" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-semibold leading-tight">InsightsGen</div>
          <div className="text-[11.5px]" style={{ color: "var(--muted)" }}>Ask your data anything</div>
        </div>
        <button className="btn" style={{ padding: 6 }} onClick={onToggleTheme} title="Toggle theme">
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        {onClose && (
          <span className="md:hidden">
            <button className="btn" style={{ padding: 6 }} onClick={onClose} title="Close"><X size={15} /></button>
          </span>
        )}
      </div>

      <div className="px-4 pb-3">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files); }}
          onClick={() => input.current?.click()}
          className="rounded-xl px-3 py-5 text-center cursor-pointer transition-colors"
          style={{ border: `1.5px dashed ${drag ? "var(--accent)" : "var(--muted)"}`, background: drag ? "var(--accent-soft)" : "transparent" }}
        >
          <Upload size={20} style={{ color: "var(--accent)", margin: "0 auto 6px" }} />
          <div className="text-sm font-medium">Drop CSV or Excel files</div>
          <div className="text-xs mt-0.5" style={{ color: "var(--muted)" }}>or click to browse · multiple files, all sheets</div>
          <input ref={input} type="file" multiple accept=".csv,.tsv,.xlsx,.xlsm,.xls" className="hidden" onChange={(e) => handleFiles(e.target.files)} />
        </div>
        <div className="flex gap-2 mt-2.5">
          <button className="btn flex-1 justify-center" onClick={onSample} disabled={busy}>
            <Database size={14} /> Load sample data
          </button>
          <button className="btn" onClick={onClear} disabled={busy || tables.length === 0} title="Remove all tables and chat">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scroll px-4 pb-4 space-y-2">
        {tables.length > 0 && (
          <div className="text-xs font-medium uppercase tracking-wide pt-1" style={{ color: "var(--muted)" }}>
            {tables.length} table{tables.length === 1 ? "" : "s"} loaded
          </div>
        )}
        {tables.map((t) => <TableCard key={t.name} t={t} onRemove={() => onRemove(t.name)} />)}
        {joins.length > 0 && (
          <div className="pt-2">
            <div className="text-xs font-medium uppercase tracking-wide mb-1.5" style={{ color: "var(--muted)" }}>Detected relationships</div>
            {joins.map((j) => (
              <div key={j.column} className="text-xs flex gap-1.5 items-start py-0.5" style={{ color: "var(--ink-2)" }}>
                <Link2 size={13} style={{ color: "var(--accent)", marginTop: 2, flexShrink: 0 }} />
                <span><span className="mono" style={{ color: "var(--ink)" }}>{j.column}</span> links {j.tables.map((t, i) => <span key={t}>{i > 0 ? " · " : ""}<span className="mono">{t}</span></span>)}</span>
              </div>
            ))}
          </div>
        )}
        {tables.length > 1 && joins.length === 0 && (
          <div className="text-xs pt-1" style={{ color: "var(--muted)" }}>No shared columns between tables. Cross-file questions may need explicit column names.</div>
        )}
      </div>

      <div className="px-4 py-3 text-[11.5px] leading-snug" style={{ color: "var(--muted)", borderTop: "1px solid var(--border)" }}>
        <div>Model <span className="mono">{summary?.model ?? "openai/gpt-oss-120b"}</span> via Groq · engine DuckDB</div>
        <div className="mt-1">Your rows never leave this app. The model only sees column names, types and 3 sample rows.</div>
      </div>
    </aside>
  );
}
