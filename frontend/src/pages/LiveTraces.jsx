import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Bell, Pause, Play, Radio, RefreshCw, Zap } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import TraceTable from '../components/trace/TraceTable';
import { useApp } from '../contexts/AppContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatDecimal, formatMs, formatNumber, timeAgo } from '../utils/format';

const STATUS_FILTERS = [
  { value: '', label: 'All traces' },
  { value: 'error', label: 'Errors' },
  { value: 'slow', label: 'Slow' },
  { value: 'success', label: 'Success' },
];

function MetricTile({ label, value, hint, icon: Icon, tone = 'blue' }) {
  const tones = {
    blue: 'bg-blue-50 text-primary',
    orange: 'bg-orange-50 text-accent',
    green: 'bg-emerald-50 text-success',
    pink: 'bg-pink-50 text-danger',
  };
  return (
    <div className="rounded-widget border border-line bg-white px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted">{label}</span>
        <span className={`grid h-6 w-6 place-items-center rounded-md ${tones[tone]}`}>
          <Icon size={12} />
        </span>
      </div>
      <p className="mt-1.5 text-[20px] font-extrabold leading-none text-ink">{value}</p>
      <p className="mt-1 text-[9.5px] font-medium text-muted">{hint}</p>
    </div>
  );
}

export default function LiveTraces() {
  const navigate = useNavigate();
  const { range, services: servicesPayload } = useApp();
  const [paused, setPaused] = useState(false);
  const [status, setStatus] = useState('');
  const [service, setService] = useState('');

  const tracesQuery = useApi(
    () =>
      api.traces({
        page_size: 15,
        page: 1,
        sort: 'start_time',
        order: 'desc',
        range,
        ...(status ? { status } : {}),
        ...(service ? { service } : {}),
      }),
    [status, service, range],
    { interval: paused ? 0 : 2500, enabled: !paused }
  );

  const telemetry = useApi(() => api.telemetryStats(), [paused], {
    interval: paused ? 0 : 3000,
    enabled: !paused,
  });
  const eventsQuery = useApi(() => api.events({ limit: 12, hours: 24 }), [], {
    interval: 8000,
  });

  const counters = telemetry.data?.counters || {};
  const buffer = telemetry.data?.buffer || {};
  const services = servicesPayload?.services || [];

  return (
    <>
      <PageHeading
        eyebrow="Streaming"
        title="Live Traces"
        subtitle="Requests as they are aggregated, sampled and indexed by the collector."
        actions={
          <>
            <Button
              variant={paused ? 'primary' : 'secondary'}
              size="sm"
              icon={paused ? Play : Pause}
              onClick={() => setPaused((value) => !value)}
            >
              {paused ? 'Resume stream' : 'Pause stream'}
            </Button>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={tracesQuery.refresh}>
              Refresh
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile
          label="Traces / window"
          value={formatNumber(tracesQuery.data?.total)}
          hint={`Selected range · ${range}`}
          icon={Activity}
          tone="blue"
        />
        <MetricTile
          label="Spans received"
          value={formatNumber(counters.spans_received)}
          hint={`${formatNumber(counters.spans_enqueued)} enqueued to buffer`}
          icon={Zap}
          tone="green"
        />
        <MetricTile
          label="Buffer depth"
          value={formatNumber(buffer.depth)}
          hint={`${formatNumber(buffer.pending)} pending · backend ${buffer.backend || '—'}`}
          icon={Radio}
          tone="orange"
        />
        <MetricTile
          label="Ingest latency"
          value={formatMs(counters.ingest_latency_ms)}
          hint={`Spill queue ${formatNumber(telemetry.data?.spill_queue?.depth)} spans`}
          icon={RefreshCw}
          tone="pink"
        />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Trace tail"
            subtitle={paused ? 'Stream paused — showing the last snapshot.' : 'Refreshing every 2.5 seconds from the collector.'}
            icon={Activity}
            action={
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${
                    paused ? 'bg-slate-100 text-muted' : 'bg-emerald-50 text-success'
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${paused ? 'bg-slate-400' : 'bg-success animate-pulse-soft'}`} />
                  {paused ? 'Paused' : 'Streaming'}
                </span>
              </div>
            }
          />

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <select
              value={status}
              onChange={(event) => setStatus(event.target.value)}
              className="h-8 cursor-pointer rounded-btn border border-line bg-white px-2.5 text-[11px] font-semibold text-ink outline-none focus:ring-2 focus:ring-primary/10"
              aria-label="Filter by status"
            >
              {STATUS_FILTERS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={service}
              onChange={(event) => setService(event.target.value)}
              className="h-8 max-w-[180px] cursor-pointer rounded-btn border border-line bg-white px-2.5 text-[11px] font-semibold text-ink outline-none focus:ring-2 focus:ring-primary/10"
              aria-label="Filter by service"
            >
              <option value="">All services</option>
              {services.map((item) => (
                <option key={item.service} value={item.service}>
                  {item.service}
                </option>
              ))}
            </select>
            <span className="ml-auto text-[10px] font-medium text-muted">
              {formatDecimal(counters.spans_enqueued, 0)} spans accepted since start
            </span>
          </div>

          <div className="mt-3">
            <TraceTable
              traces={tracesQuery.data?.items || []}
              loading={tracesQuery.loading}
              error={tracesQuery.error}
              onRetry={tracesQuery.refresh}
              emptyTitle="No traces in this window"
              emptyDescription="Generate traffic from the Benchmarks page or call the demo gateway to see live telemetry."
            />
          </div>

          <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
            <span className="text-[10px] font-medium text-muted">
              Showing latest {Math.min(15, tracesQuery.data?.total || 0)} of {formatNumber(tracesQuery.data?.total)}
            </span>
            <Button variant="ghost" size="sm" icon={Bell} onClick={() => navigate('/traces')}>
              Open explorer
            </Button>
          </div>
        </Card>

        <Card className="flex flex-col p-5">
          <CardHeader title="Event stream" subtitle="Collector-wide activity feed." icon={Radio} />
          <div className="mt-3 flex-1">
            {eventsQuery.loading ? (
              <p className="text-[11px] font-medium text-muted">Loading events…</p>
            ) : (eventsQuery.data?.items || []).length === 0 ? (
              <p className="rounded-widget border border-dashed border-line px-4 py-8 text-center text-[11px] font-medium text-muted">
                No events yet.
              </p>
            ) : (
              <ol className="relative space-y-3 border-l border-line pl-3.5">
                {(eventsQuery.data?.items || []).slice(0, 8).map((event) => (
                  <li key={event.id} className="relative">
                    <span
                      className={`absolute -left-[18px] top-1 h-2 w-2 rounded-full ring-2 ring-white ${
                        event.level === 'error'
                          ? 'bg-danger'
                          : event.level === 'warning'
                            ? 'bg-accent'
                            : 'bg-primary'
                      }`}
                    />
                    <p className="text-[11px] font-semibold leading-snug text-ink">{event.message}</p>
                    <div className="mt-0.5 flex items-center gap-1.5">
                      <Badge status={event.level === 'error' ? 'error' : event.level === 'warning' ? 'warning' : 'success'} label={event.category} dot={false} />
                      <span className="text-[9px] font-medium text-muted">{timeAgo(event.ts)}</span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div className="mt-4 rounded-widget bg-canvas/70 px-3.5 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted">Workers</p>
            <div className="mt-1.5 grid grid-cols-2 gap-1.5">
              {Object.entries(telemetry.data?.workers || {}).map(([name, worker]) => (
                <div key={name} className="flex items-center justify-between gap-2 rounded-md bg-white px-2 py-1">
                  <span className="truncate text-[9.5px] font-semibold capitalize text-muted">{name}</span>
                  <span className={`text-[9px] font-bold ${worker.running ? 'text-success' : 'text-danger'}`}>
                    {worker.running ? 'up' : 'down'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </>
  );
}
