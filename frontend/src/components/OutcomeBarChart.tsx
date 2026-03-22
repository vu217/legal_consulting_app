import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SimilarCase } from "../types";

const COLOR_MAP: Record<string, string> = {
  acquitted: "#4ade80",
  allowed: "#4ade80",
  upheld: "#4ade80",
  quashed: "#4ade80",
  convicted: "#f87171",
  dismissed: "#f87171",
  sentenced: "#f87171",
  unknown: "#9ca3af",
};

function colorFor(outcome: string): string {
  const o = outcome.toLowerCase();
  for (const [k, v] of Object.entries(COLOR_MAP)) {
    if (o.includes(k)) return v;
  }
  return "#9ca3af";
}

export function OutcomeBarChart({ cases }: { cases: SimilarCase[] }) {
  const data = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of cases) {
      const o = c.outcome || "unknown";
      counts.set(o, (counts.get(o) || 0) + 1);
    }
    return Array.from(counts.entries()).map(([outcome, count]) => ({
      outcome,
      count,
      fill: colorFor(outcome),
    }));
  }, [cases]);

  if (!data.length) return null;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 28 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
        <XAxis dataKey="outcome" tick={{ fill: "#8b949e", fontSize: 11 }} stroke="#21262d" />
        <YAxis tick={{ fill: "#8b949e", fontSize: 11 }} stroke="#21262d" />
        <Tooltip
          contentStyle={{ background: "#161b22", border: "1px solid #30363d", color: "#e6edf3" }}
        />
        <Bar dataKey="count" radius={[4, 4, 0, 0]}>
          {data.map((e, i) => (
            <Cell key={i} fill={e.fill} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
