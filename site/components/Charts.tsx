"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/* A categorical palette that stays legible in both light and dark themes.
   Ordered so adjacent series are distinguishable for the most common colour-vision
   deficiencies (no red/green pairing in the first positions). */
export const PALETTE = [
  "#3d7ab8", "#e08a3c", "#4d9e7a", "#a76fbf", "#c2554d",
  "#7d8fa1", "#d4b23f", "#6bA6c9", "#9c6b4f", "#5e6f9e",
];

const AXIS = { fontSize: 12, fill: "var(--text-muted)" };

const tooltipStyle = {
  contentStyle: {
    background: "var(--bg-raised)",
    border: "1px solid var(--border-strong)",
    borderRadius: 6,
    fontSize: 13,
    color: "var(--text)",
  },
  labelStyle: { color: "var(--text)", fontWeight: 600 },
  itemStyle: { color: "var(--text)" },
};

/* ------------------------------------------------------------------ line */
export function TrendLine({
  data,
  lines,
  yLabel,
}: {
  data: Record<string, unknown>[];
  lines: { key: string; name: string }[];
  yLabel?: string;
}) {
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="year" tick={AXIS} stroke="var(--border-strong)" />
          <YAxis
            tick={AXIS}
            stroke="var(--border-strong)"
            width={48}
            label={
              yLabel
                ? { value: yLabel, angle: -90, position: "insideLeft", style: AXIS }
                : undefined
            }
          />
          <Tooltip {...tooltipStyle} />
          {lines.length > 1 && <Legend wrapperStyle={{ fontSize: 12.5 }} />}
          {lines.map((l, i) => (
            <Line
              key={l.key}
              type="monotone"
              dataKey={l.key}
              name={l.name}
              stroke={PALETTE[i % PALETTE.length]}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------ bar */
export function Bars({
  data,
  bars,
  xKey = "year",
  stacked = false,
  layout = "horizontal",
  height,
}: {
  data: Record<string, unknown>[];
  bars: { key: string; name: string; color?: string }[];
  xKey?: string;
  stacked?: boolean;
  layout?: "horizontal" | "vertical";
  height?: number;
}) {
  const vertical = layout === "vertical";
  return (
    <div className="chart-box" style={height ? { height } : undefined}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout={layout}
          margin={{ top: 8, right: 12, left: vertical ? 8 : 4, bottom: 4 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={vertical} horizontal={!vertical} />
          {vertical ? (
            <>
              <XAxis type="number" tick={AXIS} stroke="var(--border-strong)" />
              {/* interval={0} forces every category label to render. Recharts otherwise
                  drops labels to avoid overlap, which silently hid half of a 20-company
                  axis and made the chart look like it had fewer bars than it did. */}
              <YAxis
                type="category"
                dataKey={xKey}
                tick={AXIS}
                stroke="var(--border-strong)"
                width={150}
                interval={0}
              />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} tick={AXIS} stroke="var(--border-strong)" />
              <YAxis tick={AXIS} stroke="var(--border-strong)" width={48} />
            </>
          )}
          <Tooltip {...tooltipStyle} cursor={{ fill: "var(--bg-subtle)" }} />
          {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 12.5 }} />}
          {bars.map((b, i) => (
            <Bar
              key={b.key}
              dataKey={b.key}
              name={b.name}
              stackId={stacked ? "a" : undefined}
              fill={b.color ?? PALETTE[i % PALETTE.length]}
              radius={stacked ? 0 : [3, 3, 0, 0]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ------------------------------------------------------------------ pie */
export function Donut({
  data,
  nameKey = "name",
  valueKey = "value",
}: {
  data: Record<string, unknown>[];
  nameKey?: string;
  valueKey?: string;
}) {
  return (
    <div className="chart-box">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey={valueKey}
            nameKey={nameKey}
            innerRadius="46%"
            outerRadius="76%"
            paddingAngle={1.5}
            stroke="var(--bg-raised)"
            strokeWidth={2}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Pie>
          <Tooltip {...tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ChartLegend({ items }: { items: { label: string; value?: string }[] }) {
  return (
    <div className="legend">
      {items.map((it, i) => (
        <span className="item" key={it.label}>
          <span className="swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
          {it.label}
          {it.value ? <span className="mono">&nbsp;{it.value}</span> : null}
        </span>
      ))}
    </div>
  );
}
