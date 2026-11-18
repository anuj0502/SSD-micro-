import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CloudUpload,
  Database,
  Filter,
  Gauge,
  Package,
  Radio,
  Server,
  Timer,
  Waypoints,
  Zap,
} from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import StatCard from '../components/ui/StatCard';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import PerformanceChart from '../components/charts/PerformanceChart';
import TraceTable from '../components/trace/TraceTable';
import { ErrorState, Skeleton } from '../components/ui/Feedback';
import { useApp } from '../contexts/AppContext';
import useApi from '../hooks/useApi';
import useLiveFeed from '../hooks/useLiveFeed';
import api from '../services/api';
import {
  formatDecimal,
  formatMs,
  formatNumber,
  formatPercent,
  timeAgo,
} from '../utils/format';

const EVENT_ICONS = {
  sampling: Filter,
  batch: Package,
  storage: CloudUpload,
  fault: Zap,
  benchmark: Gauge,
  telemetry: Activity,
  system: Server,
  pipeline: Waypoints,
};

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning, Operator.';
  if (hour < 18) return 'Good afternoon, Operator.';
  return 'Good evening, Operator.';
}

/**
 * Real period-over-period comparison: the first half of the selected window
 * versus the second half, computed from the same timeseries the chart renders.
 */
function halfTrend(points, key, inverse = false) {
  if (!points || points.length < 4) return null;
  const half = Math.floor(points.length / 2);
  const sum = (rows) => rows.reduce((total, row) => total + Number(row[key] || 0), 0);
  const first = sum(points.slice(0, half));
  const second = sum(points.slice(half));
  if (first === 0) return null;
  const pct = ((second - first) / first) * 100;
  const improving = inverse ? pct < 0 : pct > 0;
  return {
    value: `${pct >= 0 ? '+' : ''}${pct.toFixed(0)}%`,
    direction: pct >= 0 ? 'up' : 'down',
    tone: Math.abs(pct) < 0.5 ? 'neutral' : improving ? 'positive' : 'negative',
  };
}

function ServiceHealthCard({ service, onInspect }) {
  return (
    <div className="rounded-widget border border-line bg-white p-3.5 transition-all duration-300 hover:shadow-card">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-50 text-slate-500">
            <Server size={13} />
          </span>
          <p className="truncate text-[12px] font-bold text-ink">{service.service}</p>
        </div>
        <Badge status={service.health} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-1.5">
        <div>
          <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Requests</p>
          <p className="mt-0.5 text-[11.5px] font-bold text-ink">{formatNumber(service.requests)}</p>
        </div>
        <div>
          <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Errors</p>
          <p className={`mt-0.5 text-[11.5px] font-bold ${service.error_rate >= 2 ? 'text-danger' : 'text-ink'}`}>
            {formatPercent(service.error_rate)}
          </p>
        </div>
        <div>
          <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Latency</p>
          <p className="mt-0.5 text-[11.5px] font-bold text-ink">{formatMs(service.avg_latency_ms)}</p>
        </div>
      </div>
      <div className="mt-2.5 flex items-center justify-between border-t border-line pt-2">
        <span className="text-[9.5px] font-medium text-muted">Active {timeAgo(service.last_seen)}</span>
        <button
          type="button"
          onClick={() => onInspect(service.service)}
          className="inline-flex items-center gap-1 text-[10px] font-bold text-primary transition-colors hover:text-blue-700"
        >
          Inspect <ArrowRight size={10} />
        </button>
      </div>
    </div>
  );
}

export default function Overview() {
  const navigate = useNavigate();
  const { range, live, refreshTick } = useApp();
  const [metric, setMetric] = useState('requests');
  const query = useApi(() => api.overview(range), [range, refreshTick], { interval: live ? 10000 : 0 });
  const { snapshot, connected } = useLiveFeed(range, live);

  const data = query.data;
  const liveMetrics = live ? snapshot?.overview : null;
  const metrics = useMemo(
    () => (liveMetrics ? { ...(data?.metrics || {}), ...liveMetrics } : data?.metrics || {}),
    [data?.metrics, liveMetrics]
  );
  const services = live && snapshot?.services?.length ? snapshot.services : data?.services || [];
  const points = data?.timeseries || [];
  const recentTraces = data?.recent_traces || [];
  const events = data?.recent_events || [];

  if (query.loading && !data) {
    return (
      <>
        <PageHeading title={greeting()} subtitle="Here's what's happening across your distributed systems." />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-[150px] rounded-card" />
          ))}
        </div>
        <div className="mt-5 grid gap-4 xl:grid-cols-3">
          <Skeleton className="h-[380px] rounded-card xl:col-span-2" />
          <Skeleton className="h-[380px] rounded-card" />
        </div>
      </>
    );
  }

  if (query.error && !data) {
    return (
      <>
        <PageHeading title={greeting()} subtitle="Here's what's happening across your distributed systems." />
        <ErrorState message={query.error} onRetry={query.refresh} />
      </>
    );
  }

  const sampling = data?.sampling || {};
  const visibleServices = [...services].sort((a, b) => b.requests - a.requests).slice(0, 4);

  return (
    <>
      <PageHeading
        title={greeting()}
        subtitle="Here's what's happening across your distributed systems."
        actions={
          <>
            {data?.demo?.enabled && (
              <span title="Metrics are derived from simulated telemetry, not production traffic" className="inline-flex h-9 items-center gap-2 rounded-btn border border-amber-200 bg-amber-50 px-3 text-[11px] font-semibold text-amber-800">
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                Demo Mode · Simulated Data
              </span>
            )}
            <span className="inline-flex h-9 items-center gap-2 rounded-btn border border-line bg-white px-3 text-[11px] font-semibold text-muted">
              <span className={`h-1.5 w-1.5 rounded-full ${connected ? 'bg-success animate-pulse-soft' : live ? 'bg-accent' : 'bg-slate-300'}`} />
              {live ? (connected ? 'Live feed connected' : 'Connecting feed…') : 'Live paused'}
            </span>
            <Button variant="secondary" size="sm" icon={Activity} onClick={() => navigate('/live')}>
              Live traces
            </Button>
          </>
        }
      />

      {/* Statistics row */}
      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Total Traces"
          value={formatNumber(metrics.total_traces)}
          hint={`${formatNumber(metrics.total_spans)} spans indexed`}
          icon={Waypoints}
          tone="blue"
          trend={halfTrend(points, 'requests')}
        />
        <StatCard
          label="Error Rate"
          value={formatPercent(metrics.error_rate)}
          hint={`${formatNumber(metrics.error_traces)} failed traces`}
          icon={AlertTriangle}
          tone="pink"
          trend={halfTrend(points, 'errors', true)}
        />
        <StatCard
          label="Average Latency"
          value={formatMs(metrics.avg_latency_ms)}
          hint={`P50 ${formatMs(metrics.p50_latency_ms)}`}
          icon={Timer}
          tone="orange"
          trend={halfTrend(points, 'latency_ms', true)}
        />
        <StatCard
          label="P95 Latency"
          value={formatMs(metrics.p95_latency_ms)}
          hint={`P99 ${formatMs(metrics.p99_latency_ms)}`}
          icon={Gauge}
          tone="purple"
        />
        <StatCard
          label="Sampling Rate"
          value={formatPercent(metrics.sampling_rate)}
          hint={`${formatNumber(metrics.retained_traces)} of ${formatNumber(metrics.total_traces)} retained`}
          icon={Filter}
          tone="green"
        />
        <StatCard
          label="Ingestion Throughput"
          value={`${formatDecimal(metrics.throughput_spans_per_s, 1)}`}
          hint={`${formatNumber(metrics.recent_spans_60s)} spans in last 60s`}
          icon={Zap}
          tone="blue"
          trend={halfTrend(points, 'throughput')}
        />
      </div>

      {/* Analytics + service health */}
      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="System Performance"
            subtitle="Telemetry activity across your services."
            icon={Activity}
            action={
              <span className="rounded-full bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-muted">
                {range} window
              </span>
            }
          />
          <div className="mt-4">
            <PerformanceChart
              points={points}
              metric={metric}
              onMetricChange={setMetric}
              loading={query.loading && !points.length}
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader
            title="Service Health"
            subtitle="Observed per-service performance."
            icon={Server}
            action={
              <button
                type="button"
                onClick={() => navigate('/services')}
                className="text-[10.5px] font-bold text-primary hover:text-blue-700"
              >
                View map
              </button>
            }
          />
          <div className="mt-4 space-y-2.5">
            {visibleServices.length === 0 ? (
              <p className="rounded-widget border border-dashed border-line px-4 py-8 text-center text-[11px] font-medium text-muted">
                No service telemetry indexed yet.
              </p>
            ) : (
              visibleServices.map((service) => (
                <ServiceHealthCard
                  key={service.service}
                  service={service}
                  onInspect={(name) => navigate(`/services?service=${encodeURIComponent(name)}`)}
                />
              ))
            )}
          </div>
        </Card>
      </div>

      {/* Recent traces + events */}
      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Recent Traces"
            subtitle="Latest requests indexed from the telemetry pipeline."
            icon={Waypoints}
            action={
              <button
                type="button"
                onClick={() => navigate('/traces')}
                className="inline-flex items-center gap-1 text-[10.5px] font-bold text-primary hover:text-blue-700"
              >
                Open explorer <ArrowRight size={11} />
              </button>
            }
          />
          <div className="mt-3">
            <TraceTable
              traces={recentTraces}
              loading={query.loading}
              error={query.error}
              onRetry={query.refresh}
              compact
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader
            title="Recent System Events"
            subtitle="Collector, sampling and storage activity."
            icon={Radio}
          />
          <div className="mt-3">
            {events.length === 0 ? (
              <p className="rounded-widget border border-dashed border-line px-4 py-8 text-center text-[11px] font-medium text-muted">
                No events recorded yet.
              </p>
            ) : (
              <ol className="space-y-2.5">
                {events.slice(0, 6).map((event) => {
                  const Icon = EVENT_ICONS[event.category] || CheckCircle2;
                  return (
                    <li key={event.id} className="flex items-start gap-2.5">
                      <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-slate-50 text-slate-500">
                        <Icon size={12} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[11px] font-semibold leading-snug text-ink">{event.message}</p>
                        <p className="mt-0.5 text-[9.5px] font-medium text-muted">
                          {timeAgo(event.ts)} · {event.category}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </div>
          {sampling?.retention_rate !== undefined ? (
            <div className="mt-4 rounded-widget bg-canvas/70 px-3.5 py-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-wider text-muted">Tail sampler</span>
                <span className="text-[10px] font-bold text-ink">{formatPercent(sampling.retention_rate)}</span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${Math.min(100, Number(sampling.retention_rate) || 0)}%` }}
                />
              </div>
              <p className="mt-1.5 text-[9.5px] font-medium text-muted">
                {formatNumber(sampling.evaluated)} traces evaluated
              </p>
            </div>
          ) : null}
        </Card>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-[10px] font-medium text-muted">
        <span className="inline-flex items-center gap-1.5">
          <Database size={11} /> Data sources: collector REST API + live WebSocket
        </span>
        <span>Window {range} · {points.length} buckets</span>
      </div>
    </>
  );
}
