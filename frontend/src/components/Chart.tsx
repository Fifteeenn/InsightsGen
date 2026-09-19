import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ChartPayload } from "../types";
import { dateFormatter, fmtNumber } from "../format";

const SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)", "var(--s7)", "var(--s8)"];

const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10,
    color: "var(--ink)", fontSize: 13, boxShadow: "0 4px 16px rgba(0,0,0,.08)",
  },
  labelStyle: { color: "var(--ink-2)", marginBottom: 4 },
  itemStyle: { color: "var(--ink)", padding: 0 },
  cursor: { stroke: "var(--muted)", strokeDasharray: "3 3" },
};

const axisTick = { fill: "var(--muted)", fontSize: 12 };
const legendStyle = { fontSize: 12.5, color: "var(--ink-2)" };

export default function Chart({ chart }: { chart: ChartPayload }) {
  const { kind, x, series, data, horizontal } = chart;
  if (!x || series.length === 0 || data.length === 0) return null;
  const multi = series.length > 1;
  const valueFmt = (v: unknown) => fmtNumber(v);

  if (kind === "line") {
    const xf = dateFormatter(data.map((d) => d[x]));
    return (
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey={x} tickFormatter={xf} tick={axisTick} axisLine={{ stroke: "var(--grid)" }} tickLine={false} minTickGap={24} />
          <YAxis tickFormatter={(v) => fmtNumber(v, true)} tick={axisTick} axisLine={false} tickLine={false} width={56} />
          <Tooltip {...tooltipStyle} labelFormatter={(l) => xf(l)} formatter={(v: unknown) => valueFmt(v)} />
          {multi && <Legend wrapperStyle={legendStyle} iconType="plainline" />}
          {series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={SERIES[i % SERIES.length]}
              strokeWidth={2} dot={data.length <= 40 ? { r: 3, strokeWidth: 0, fill: SERIES[i % SERIES.length] } : false}
              activeDot={{ r: 5, stroke: "var(--surface)", strokeWidth: 2 }} isAnimationActive={data.length <= 200} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (kind === "bar") {
    const height = horizontal ? Math.max(260, 30 * data.length + 60) : 320;
    const catAxisProps = { dataKey: x, tick: axisTick, axisLine: { stroke: "var(--grid)" }, tickLine: false as const };
    const numAxisProps = { tickFormatter: (v: unknown) => fmtNumber(v, true), tick: axisTick, axisLine: false as const, tickLine: false as const };
    return (
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 12, right: 16, bottom: 4, left: 4 }} barCategoryGap="30%">
          <CartesianGrid horizontal={!horizontal} vertical={horizontal} stroke="var(--grid)" />
          {/* Recharts discovers axes by direct child type, so no fragments here. */}
          {horizontal
            ? <XAxis type="number" {...numAxisProps} />
            : <XAxis type="category" {...catAxisProps} interval={0} angle={data.length > 6 ? -20 : 0} textAnchor={data.length > 6 ? "end" : "middle"} height={data.length > 6 ? 56 : 30} />}
          {horizontal
            ? <YAxis type="category" {...catAxisProps} width={Math.min(200, 8 * Math.max(...data.map((d) => String(d[x] ?? "").length)) + 16)} interval={0} />
            : <YAxis type="number" {...numAxisProps} width={56} />}
          <Tooltip {...tooltipStyle} cursor={{ fill: "var(--surface-2)" }} formatter={(v: unknown) => valueFmt(v)} />
          {multi && <Legend wrapperStyle={legendStyle} iconType="circle" />}
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.name} fill={SERIES[i % SERIES.length]} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={48} isAnimationActive={data.length <= 200} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (kind === "scatter") {
    const y = series[0];
    return (
      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 12, right: 16, bottom: 8, left: 4 }}>
          <CartesianGrid stroke="var(--grid)" />
          <XAxis dataKey={x} type="number" name={chart.x_label ?? x} tickFormatter={(v) => fmtNumber(v, true)} tick={axisTick} axisLine={{ stroke: "var(--grid)" }} tickLine={false} />
          <YAxis dataKey={y.key} type="number" name={y.name} tickFormatter={(v) => fmtNumber(v, true)} tick={axisTick} axisLine={false} tickLine={false} width={56} />
          <Tooltip {...tooltipStyle} formatter={(v: unknown) => valueFmt(v)} />
          <Scatter data={data} fill="var(--s1)" fillOpacity={0.8} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }
  return null;
}
