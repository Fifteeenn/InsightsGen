import { fmtNumber, humanize, isNumeric } from "../format";

const MAX_ROWS = 200;

export default function ResultTable({ columns, rows, total }: { columns: string[]; rows: unknown[][]; total: number }) {
  if (columns.length === 0) return <div className="text-sm" style={{ color: "var(--muted)" }}>No rows returned.</div>;
  const shown = rows.slice(0, MAX_ROWS);
  const numericCol = columns.map((_, i) => shown.some((r) => isNumeric(r[i])) && shown.every((r) => r[i] === null || isNumeric(r[i])));
  return (
    <div>
      <div className="overflow-auto scroll rounded-lg" style={{ maxHeight: 360, border: "1px solid var(--grid)" }}>
        <table className="result">
          <thead>
            <tr>{columns.map((c) => <th key={c}>{humanize(c)}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {r.map((v, j) => (
                  <td key={j} className={numericCol[j] ? "num" : ""}>
                    {v === null || v === undefined ? <span style={{ color: "var(--muted)" }}>—</span> : numericCol[j] ? fmtNumber(v) : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total > shown.length && (
        <div className="text-xs mt-1.5" style={{ color: "var(--muted)" }}>Showing {shown.length} of {total.toLocaleString()} rows. Download the CSV for all of them.</div>
      )}
    </div>
  );
}
