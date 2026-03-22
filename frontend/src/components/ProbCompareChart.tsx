import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export function ProbCompareChart({
  baseRate,
  llmEst,
  blended,
}: {
  baseRate: number;
  llmEst: number;
  blended: number;
}) {
  const data = [
    { name: "Historical base rate", value: baseRate, fill: "#60a5fa" },
    { name: "LLM estimate", value: llmEst, fill: "#a78bfa" },
    { name: "Blended", value: blended, fill: "#4ade80" },
  ];
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
        <XAxis dataKey="name" tick={{ fill: "#8b949e", fontSize: 10 }} stroke="#21262d" interval={0} angle={-12} textAnchor="end" height={48} />
        <YAxis domain={[0, 100]} tick={{ fill: "#8b949e", fontSize: 11 }} stroke="#21262d" />
        <Tooltip
          contentStyle={{ background: "#161b22", border: "1px solid #30363d", color: "#e6edf3" }}
          formatter={(v: number) => [`${v}%`, ""]}
        />
        <Bar dataKey="value" radius={[4, 4, 0, 0]}>
          {data.map((e, i) => (
            <Cell key={i} fill={e.fill} />
          ))}
          <LabelList
            dataKey="value"
            position="top"
            fill="#8b949e"
            fontSize={11}
            formatter={(v: number) => `${v}%`}
          />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
