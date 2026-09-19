import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Lightbulb, Menu, Sparkles } from "lucide-react";
import * as api from "./api";
import type { Answer, WorkspaceSummary } from "./types";
import Sidebar from "./components/Sidebar";
import AnswerCard from "./components/AnswerCard";

type Theme = "light" | "dark";

function initialTheme(): Theme {
  const saved = localStorage.getItem("insightsgen.theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export default function App() {
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [messages, setMessages] = useState<Answer[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [thinking, setThinking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const bottom = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const hasData = (summary?.tables.length ?? 0) > 0;

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("insightsgen.theme", theme);
  }, [theme]);

  const notify = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 4500);
  };

  const refreshSuggestions = useCallback(async () => {
    try {
      setSuggestions(await api.getSuggestions());
    } catch {
      setSuggestions([]);
    }
  }, []);

  // Restore a previous session (tables and chat) on reload.
  useEffect(() => {
    (async () => {
      try {
        const s = await api.getSession();
        setSummary(s);
        setMessages(s.messages ?? []);
        if (s.tables.length > 0) void refreshSuggestions();
      } catch (e) {
        notify((e as Error).message);
      }
    })();
  }, [refreshSuggestions]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  const applySummary = async (s: WorkspaceSummary) => {
    setSummary(s);
    setSuggestions([]);
    if (s.tables.length > 0) await refreshSuggestions();
  };

  const run = async (fn: () => Promise<WorkspaceSummary>) => {
    setBusy(true);
    try {
      await applySummary(await fn());
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onUpload = (files: File[]) => run(() => api.uploadFiles(files));
  const onSample = () => run(() => api.loadSample());
  const onRemove = (name: string) => run(() => api.removeTable(name));
  const onClear = async () => {
    setBusy(true);
    try {
      await api.resetSession();
      setSummary(await api.getSession());
      setMessages([]);
      setSuggestions([]);
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || thinking || !hasData) return;
    setQuestion("");
    setThinking(true);
    const placeholder: Answer = {
      question: text, title: "", narrative: "", explanation: "", sql: null, chart_hint: "table", clarification: null,
      error: null, attempts: [], truncated: false, elapsed_ms: 0, healed: false, ok: false, columns: [], rows: [], row_count: 0, chart: null,
    };
    setMessages((m) => [...m, placeholder]);
    try {
      const a = await api.ask(text);
      setMessages((m) => [...m.slice(0, -1), a]);
    } catch (e) {
      setMessages((m) => [...m.slice(0, -1), { ...placeholder, error: (e as Error).message }]);
    } finally {
      setThinking(false);
      inputRef.current?.focus();
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  };

  const sidebar = (
    <Sidebar summary={summary} busy={busy} onUpload={onUpload} onSample={onSample} onRemove={onRemove} onClear={onClear}
      theme={theme} onToggleTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))} onClose={() => setSidebarOpen(false)} />
  );

  return (
    <div className="h-dvh overflow-hidden grid grid-rows-[minmax(0,1fr)] md:grid-cols-[320px_1fr]">
      <div className="hidden md:block h-full min-h-0">{sidebar}</div>
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0" style={{ background: "rgba(0,0,0,.4)" }} onClick={() => setSidebarOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-[320px] max-w-[88vw]">{sidebar}</div>
        </div>
      )}

      <main className="h-full min-h-0 flex flex-col min-w-0">
        <header className="md:hidden flex items-center gap-2 px-4 py-3" style={{ borderBottom: "1px solid var(--border)", background: "var(--surface)" }}>
          <button className="btn" style={{ padding: 6 }} onClick={() => setSidebarOpen(true)}><Menu size={16} /></button>
          <span className="font-semibold">InsightsGen</span>
          {hasData && <span className="text-xs ml-auto" style={{ color: "var(--muted)" }}>{summary!.tables.length} table{summary!.tables.length === 1 ? "" : "s"}</span>}
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto scroll">
          <div className="max-w-[860px] mx-auto px-4 sm:px-6 py-6 space-y-5">
            {!hasData && (
              <div className="pt-10 sm:pt-20 text-center rise">
                <div className="inline-flex items-center justify-center rounded-2xl mb-4" style={{ width: 56, height: 56, background: "var(--accent-soft)" }}>
                  <Sparkles size={26} style={{ color: "var(--accent)" }} />
                </div>
                <h1 className="text-2xl sm:text-[28px] font-semibold m-0">Ask your data anything</h1>
                <p className="mt-2 mb-6 max-w-[520px] mx-auto" style={{ color: "var(--ink-2)" }}>
                  Upload one or more CSV or Excel files, then ask questions in plain English. Every answer is computed exactly and shows the query behind it.
                </p>
                <button className="btn btn-primary" onClick={onSample} disabled={busy}>
                  {busy ? "Loading…" : "Try the sample dataset"}
                </button>
                <div className="grid sm:grid-cols-3 gap-3 mt-10 text-left">
                  {[
                    ["Exact, not estimated", "Your question becomes a SQL query run by DuckDB. The model never does arithmetic."],
                    ["Works across files", "Shared columns are detected automatically so you can ask about orders and customers together."],
                    ["Shows its work", "Every answer includes the query, the result table and a chart when the shape calls for one."],
                  ].map(([h, b]) => (
                    <div key={h} className="card p-4">
                      <div className="font-medium text-sm">{h}</div>
                      <div className="text-[13px] mt-1" style={{ color: "var(--ink-2)" }}>{b}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hasData && messages.length === 0 && (
              <div className="pt-8 sm:pt-16 rise">
                <h1 className="text-2xl font-semibold m-0">What would you like to know?</h1>
                <p className="mt-1 mb-5" style={{ color: "var(--ink-2)" }}>
                  {summary!.tables.length} table{summary!.tables.length === 1 ? "" : "s"} ready
                  {summary!.joins.length > 0 ? `, ${summary!.joins.length} relationship${summary!.joins.length === 1 ? "" : "s"} detected` : ""}. Try one of these or type your own.
                </p>
                {suggestions.length === 0 ? (
                  <div className="flex items-center gap-2 text-sm" style={{ color: "var(--muted)" }}>
                    <span className="dot" /><span className="dot" /><span className="dot" /> Reading your schema for good questions…
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((s) => (
                      <button key={s} className="chip" onClick={() => submit(s)}><Lightbulb size={13} className="inline mr-1.5 -mt-0.5" />{s}</button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {messages.map((a, i) => (
              <div key={i} className="space-y-3">
                <div className="flex justify-end">
                  <div className="rounded-2xl rounded-br-md px-4 py-2.5 max-w-[80%]" style={{ background: "var(--accent)", color: "#fff" }}>{a.question}</div>
                </div>
                {i === messages.length - 1 && thinking ? (
                  <div className="card p-4 flex items-center gap-3 text-sm" style={{ color: "var(--ink-2)" }}>
                    <span className="flex gap-1"><span className="dot" /><span className="dot" /><span className="dot" /></span>
                    Writing the query and computing the answer…
                  </div>
                ) : (
                  <AnswerCard a={a} />
                )}
              </div>
            ))}

            {hasData && messages.length > 0 && !thinking && suggestions.length > 0 && (
              <div className="flex gap-2 overflow-x-auto scroll pb-1 pt-1">
                {suggestions.map((s) => (
                  <button key={s} className="chip whitespace-nowrap" style={{ fontSize: 12.5, padding: "5px 10px" }} onClick={() => submit(s)}>{s}</button>
                ))}
              </div>
            )}
            <div ref={bottom} />
          </div>
        </div>

        <div className="px-4 sm:px-6 pb-4 pt-2" style={{ background: "linear-gradient(to top, var(--bg) 70%, transparent)" }}>
          <div className="max-w-[860px] mx-auto card flex items-end gap-2 p-2 pl-4" style={{ boxShadow: "0 6px 24px rgba(0,0,0,.06)" }}>
            <textarea
              ref={inputRef}
              rows={1}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={onKey}
              disabled={!hasData || thinking}
              placeholder={hasData ? "Ask a question about your data… e.g. total revenue by month" : "Upload data or load the sample to start"}
              className="flex-1 resize-none bg-transparent border-0 outline-none py-2 text-[15px]"
              style={{ color: "var(--ink)", maxHeight: 140 }}
              onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = `${Math.min(t.scrollHeight, 140)}px`; }}
            />
            <button className="btn btn-primary" style={{ padding: 8, borderRadius: 10 }} onClick={() => submit()} disabled={!hasData || thinking || !question.trim()} title="Send">
              <ArrowUp size={16} />
            </button>
          </div>
          <div className="text-center text-[11px] mt-2" style={{ color: "var(--muted)" }}>
            Answers are computed by SQL over your files. Open “How I computed this” to verify any number.
          </div>
        </div>
      </main>

      {toast && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 card px-4 py-2.5 text-sm rise" style={{ borderColor: "var(--bad)", maxWidth: "90vw" }}>
          {toast}
        </div>
      )}
    </div>
  );
}
