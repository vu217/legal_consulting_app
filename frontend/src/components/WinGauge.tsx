import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

export function WinGauge({ value }: { value: number }) {
  const color = value >= 60 ? "#4ade80" : value >= 40 ? "#facc15" : "#f87171";
  const data = [
    { name: "win", value },
    { name: "rest", value: Math.max(0, 100 - value) },
  ];
  return (
    <div style={{ position: "relative", width: "100%", height: 220 }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <Pie
            data={data}
            cx="50%"
            cy="70%"
            startAngle={180}
            endAngle={0}
            innerRadius="58%"
            outerRadius="85%"
            dataKey="value"
            stroke="none"
            isAnimationActive={false}
          >
            <Cell fill={color} />
            <Cell fill="#1f2937" />
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 36,
          textAlign: "center",
          fontSize: 42,
          fontWeight: 500,
          color,
        }}
      >
        {value}%
      </div>
    </div>
  );
}
