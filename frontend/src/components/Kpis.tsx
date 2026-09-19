export default function Kpis({ kpis }: { kpis: { label: string; value: string }[] }) {
  if (kpis.length === 0) return null;
  const cols = Math.min(kpis.length, 4);
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {kpis.slice(0, 8).map((k) => (
        <div key={k.label} className="rounded-xl px-4 py-3" style={{ background: "var(--surface-2)" }}>
          <div className="text-[11px] uppercase tracking-wide" style={{ color: "var(--ink-2)" }}>{k.label}</div>
          <div className="text-[26px] font-semibold leading-tight mt-0.5 tabular" style={{ color: "var(--ink)" }}>{k.value}</div>
        </div>
      ))}
    </div>
  );
}
