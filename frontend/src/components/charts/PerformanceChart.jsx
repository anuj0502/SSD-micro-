import { useMemo } from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { BarChart3 } from 'lucide-react';

import { EmptyState, Skeleton } from '../ui/Feedback';
import { formatMs, formatNumber, formatTime } from '../../utils/format';

const METRICS = {
  requests: { key: 'requests', label: 'Requests', color: '#0d6efd', unit: 'traces' },
  errors: { key: 'errors', label: 'Errors', color: '#ec4899', unit: 'errors' },
  latency: { key: 'latency_ms', label: 'Latency', color: '#f97316', unit: 'ms' },
  throughput: { key: 'throughput', label: 'Throughput', color: '#a855f7', unit: 'spans/s' },
};

function ChartTooltip({ active, payload, label, metric }) {
  if (!active || !payload?.length) return null;
  const config = METRICS[metric];
  const value = payload[0].value;
  const formatted =
    metric === 'latency' ? formatMs(value) : metric === 'throughput' ? `${formatNumber(value, 2)} spans/s` : formatNumber(value);
  return (
    <div className="rounded-xl bg-tooltip px-3.5 py-2.5 shadow-lg">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-1 text-[13px] font-bold text-white">
        <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full" style={{ background: config.color }} />
        {formatted}
      </p>
    </div>
  );
}

export default function PerformanceChart({ points = [], metric = 'requests', onMetricChange, loading = false }) {
  const config = METRICS[metric] || METRICS.requests;
  const total = useMemo(
    () => points.reduce((sum, point) => sum + Number(point[config.key] || 0), 0),
    [points, config.key]
  );

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-btn bg-slate-50 p-1">
          {Object.entries(METRICS).map(([key, option]) => (
            <button
              key={key}
              type="button"
              onClick={() => onMetricChange?.(key)}
              className={`rounded-[9px] px-3 py-1.5 text-[11px] font-semibold transition-all duration-300 ${
                metric === key ? 'bg-white text-ink shadow-sm' : 'text-muted hover:text-ink'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        <span className="text-[10.5px] font-semibold text-muted">
          Window total <span className="ml-1 text-ink">{metric === 'latency' ? formatMs(total / Math.max(points.length, 1)) : formatNumber(total)}</span>
          {metric === 'latency' ? ' avg' : ` ${config.unit}`}
        </span>
      </div>

      {loading ? (
        <Skeleton className="h-[268px] w-full" />
      ) : points.length === 0 ? (
        <EmptyState
          icon={BarChart3}
          title="No telemetry in this window"
          description="The chart fills with real traces as soon as the collector indexes them."
        />
      ) : (
        <div className="h-[268px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={points} margin={{ top: 8, right: 6, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id={`grad-${metric}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={config.color} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={config.color} stopOpacity={0.01} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#f3f4f6" vertical={false} />
              <XAxis
                dataKey="ts"
                tickFormatter={(value) => formatTime(value, false)}
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                axisLine={false}
                tickLine={false}
                minTickGap={28}
              />
              <YAxis
                tick={{ fontSize: 10, fill: '#94a3b8', fontWeight: 600 }}
                axisLine={false}
                tickLine={false}
                width={52}
                tickFormatter={(value) =>
                  metric === 'latency' ? formatMs(value) : formatNumber(value)
                }
              />
              <Tooltip content={<ChartTooltip metric={metric} />} cursor={{ stroke: '#e2e8f0', strokeDasharray: '4 4' }} />
              <Area
                type="monotone"
                dataKey={config.key}
                stroke={config.color}
                strokeWidth={2.2}
                fill={`url(#grad-${metric})`}
                activeDot={{ r: 4, strokeWidth: 2, stroke: '#fff' }}
                animationDuration={600}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
