import React from 'react';
import {
  ComposedChart, Bar, Line,
  XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Label,
} from 'recharts';

const data = [
  { duration: '30 s',  manualTime: 2.8,  macsTime: 0.6,  manualAcc: 98.1, macsAcc: 97.9 },
  { duration: '1 min', manualTime: 5.5,  macsTime: 3.2,  manualAcc: 97.5, macsAcc: 96.1 },
  { duration: '3 min', manualTime: 16.2, macsTime: 10.8, manualAcc: 96.5, macsAcc: 95.2 },
];

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload) return null;
  return (
    <div style={{
      background: '#fff', border: '1px solid #ccc',
      borderRadius: 4, padding: '8px 12px', fontSize: 11,
      fontFamily: 'Georgia, serif', lineHeight: 1.8,
    }}>
      <p style={{ fontWeight: 'bold', marginBottom: 4 }}>{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}:{' '}
          {p.name.includes('Acc')
            ? `${p.value.toFixed(1)}%`
            : `${p.value} min`}
        </p>
      ))}
    </div>
  );
};

export default function ComparisonChart() {
  return (
    <div style={{
      fontFamily: 'Georgia, serif',
      background: '#fff',
      border: '1px solid #d1d5db',
      boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
      borderRadius: 8,
      padding: '24px',
      maxWidth: 680,
      margin: '32px auto',
    }}>
      <p style={{ textAlign: 'center', fontSize: 13, fontWeight: 'bold', color: '#1f2937', marginBottom: 4 }}>
        Figure 2. Post-processing Time and Classification Accuracy
      </p>
      <p style={{ textAlign: 'center', fontSize: 11, color: '#6b7280', marginBottom: 16 }}>
        Manual Handling vs. MACS Automated Pipeline
      </p>

      {/* Legend */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 24, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#4b5563' }}>
          <span style={{ display: 'inline-block', width: 14, height: 14, background: '#ef9a9a', borderRadius: 2 }} />
          Manual — Time
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#4b5563' }}>
          <span style={{ display: 'inline-block', width: 14, height: 14, background: '#90caf9', borderRadius: 2 }} />
          MACS — Time
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#4b5563' }}>
          <svg width="22" height="10">
            <line x1="0" y1="5" x2="22" y2="5" stroke="#c62828" strokeWidth="2.5" strokeDasharray="5 3" />
            <circle cx="11" cy="5" r="3.5" fill="#c62828" />
          </svg>
          Manual — Accuracy
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#4b5563' }}>
          <svg width="22" height="10">
            <line x1="0" y1="5" x2="22" y2="5" stroke="#1565c0" strokeWidth="2.5" />
            <circle cx="11" cy="5" r="3.5" fill="#1565c0" />
          </svg>
          MACS — Accuracy
        </span>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={data}
          margin={{ top: 10, right: 68, left: 58, bottom: 38 }}
          barCategoryGap="30%"
          barGap={4}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />

          <XAxis
            dataKey="duration"
            tick={{ fontSize: 11, fontFamily: 'Georgia, serif', fill: '#444' }}
            axisLine={{ stroke: '#888' }}
            tickLine={false}
          >
            <Label
              value="Total Recording Duration"
              position="insideBottom"
              offset={-22}
              style={{ fontSize: 11, fontFamily: 'Georgia, serif', fill: '#555' }}
            />
          </XAxis>

          {/* LEFT Y — time */}
          <YAxis
            yAxisId="time"
            orientation="left"
            domain={[0, 20]}
            ticks={[0, 4, 8, 12, 16, 20]}
            tick={{ fontSize: 10, fontFamily: 'Georgia, serif', fill: '#555' }}
            axisLine={{ stroke: '#888' }}
            tickLine={false}
          >
            <Label
              value="Post-processing Time (min)"
              angle={-90}
              position="insideLeft"
              offset={-42}
              style={{ fontSize: 10, fontFamily: 'Georgia, serif', fill: '#555', textAnchor: 'middle' }}
            />
          </YAxis>

          {/* RIGHT Y — accuracy */}
          <YAxis
            yAxisId="acc"
            orientation="right"
            domain={[94, 99]}
            ticks={[94, 95, 96, 97, 98, 99]}
            tick={{ fontSize: 10, fontFamily: 'Georgia, serif', fill: '#555' }}
            tickFormatter={v => `${v}%`}
            axisLine={{ stroke: '#888' }}
            tickLine={false}
          >
            <Label
              value="Classification Accuracy (%)"
              angle={90}
              position="insideRight"
              offset={-48}
              style={{ fontSize: 10, fontFamily: 'Georgia, serif', fill: '#555', textAnchor: 'middle' }}
            />
          </YAxis>

          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />

          {/* Bars */}
          <Bar yAxisId="time" dataKey="manualTime" name="Manual — Time"
            fill="#ef9a9a" barSize={28} radius={[3, 3, 0, 0]} />
          <Bar yAxisId="time" dataKey="macsTime" name="MACS — Time"
            fill="#90caf9" barSize={28} radius={[3, 3, 0, 0]} />

          {/* Lines */}
          <Line yAxisId="acc" type="linear" dataKey="manualAcc"
            name="Manual — Acc"
            stroke="#c62828" strokeWidth={2.5} strokeDasharray="6 3"
            dot={{ r: 5, fill: '#c62828', stroke: '#fff', strokeWidth: 1.5 }}
            activeDot={{ r: 6 }} legendType="none" />
          <Line yAxisId="acc" type="linear" dataKey="macsAcc"
            name="MACS — Acc"
            stroke="#1565c0" strokeWidth={2.5}
            dot={{ r: 5, fill: '#1565c0', stroke: '#fff', strokeWidth: 1.5 }}
            activeDot={{ r: 6 }} legendType="none" />
        </ComposedChart>
      </ResponsiveContainer>

      <hr style={{ border: 'none', borderTop: '1px solid #e5e7eb', margin: '12px 0' }} />
      <p style={{ fontSize: 11, color: '#4b5563', lineHeight: 1.7 }}>
        <strong>Figure 2.</strong> Bars (left axis) show total post-processing time for manual
        handling (red) vs. MACS automation (blue) across three recording durations. Lines (right
        axis) show classification accuracy; manual labeling retains a marginal advantage
        (Δ ≤ 0.2 pp at 30 s, Δ ≤ 1.3 pp at 3 min), while MACS reduces post-processing
        time by up to 4.7× at shorter sessions.
      </p>
    </div>
  );
}
