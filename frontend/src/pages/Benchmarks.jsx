import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { BarChart3, FlaskConical, Gauge, Play, Timer, Zap } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback';
import { Field, Input, Select } from '../components/ui/Fields';
import { useToast } from '../contexts/ToastContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatBytes, formatDecimal, formatMs, formatNumber, formatPercent, formatTime } from '../utils/format';

const METRIC_TILES = [
  { key: 'total_requests_generated', label: 'Requests', format: (v) => formatNumber(v) },
  { key: 'total_spans_generated', label: 'Spans', format: (v) => formatNumber(v) },
  { key: 'traces_stored', label: 'Traces stored', format: (v) => formatNumber(v) },
  { key: 'sampled_traces', label: 'Sampled', format: (v) => formatNumber(v) },
  { key: 'ingestion_throughput_spans_per_s', label: 'Throughput', format: (v) => `${formatDecimal(v, 1)}/s` },
  { key: 'avg_processing_latency_ms', label: 'Avg latency', format: (v) => formatMs(v) },
  { key: 'p95_latency_ms', label: 'P95 latency', format: (v) => formatMs(v) },
  { key: 'p99_latency_ms', label: 'P99 latency', format: (v) => formatMs(v) },
  { key: 'error_rate_pct', label: 'Error rate', format: (v) => formatPercent(v) },
  { key: 'storage_consumed_bytes', label: 'Storage', format: (v) => formatBytes(v) },
  { key: 'compression_ratio', label: 'Compression', format: (v) => formatPercent(v * 100) },
  { key: 'write_operations', label: 'Writes', format: (v) => formatNumber(v) },
];

const EXPERIMENTS = [
  { value: 'sampling', label: 'Sampling on/off' },
  { value: 'batching', label: 'Batching on/off' },
  { value: 'faults', label: 'Storage outage' },
  { value: 'concurrency', label: 'Concurrency sweep' },
];

const defaultForm = {
  name: 'Pipeline benchmark',
  total_requests: 120,
  concurrency: 10,
  duration_s: 30,
  error_probability: 5,
  slow_probability: 10,
  mode: 'auto',
  experiments: [],
  success_rate: 10,
  batch_size: 100,
  outage_s: 4,
  concurrency_levels: '1,5,20',
};

function VariantChart({ variants }) {
  const rows = variants.map((variant) => ({
    name: variant.label,
    throughput: Number(variant.metrics?.ingestion_throughput_spans_per_s || 0),
  }));
  return (
    <div className="h-[220px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, left: -14, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#64748b' }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 9, fill: '#94a3b8' }} tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{ background: '#111827', border: 'none', borderRadius: 12, color: '#fff', fontSize: 11 }}
            formatter={(value) => [`${formatDecimal(value, 1)} spans/s`, 'Throughput']}
          />
          <Bar dataKey="throughput" radius={[6, 6, 0, 0]}>
            {rows.map((row, index) => (
              <Cell key={row.name} fill={index === 0 ? '#cbd5e1' : '#0d6efd'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Benchmarks() {
  const { notify } = useToast();
  const [form, setForm] = useState(defaultForm);
  const [selectedId, setSelectedId] = useState(null);
  const [starting, setStarting] = useState(false);

  const resultsQuery = useApi(() => api.benchmarkResults(20), [], { interval: 4000 });
  const results = resultsQuery.data?.runs || resultsQuery.data?.items || [];
  const selected = useMemo(
    () => results.find((run) => run.id === selectedId) || results[0] || null,
    [results, selectedId]
  );

  const run = async () => {
    setStarting(true);
    try {
      const created = await api.runBenchmark({
        name: form.name || 'Pipeline benchmark',
        total_requests: Number(form.total_requests),
        concurrency: Number(form.concurrency),
        duration_s: Number(form.duration_s),
        error_probability: Number(form.error_probability) / 100,
        slow_probability: Number(form.slow_probability) / 100,
        mode: form.mode,
        experiments: form.experiments,
        success_rate: Number(form.success_rate) / 100,
        batch_size: Number(form.batch_size),
        outage_s: Number(form.outage_s),
        concurrency_levels: String(form.concurrency_levels)
          .split(',')
          .map((value) => Number(value.trim()))
          .filter((value) => Number.isFinite(value) && value > 0),
      });
      setSelectedId(created.id);
      notify('Benchmark started. Metrics are measured from real traffic through the running collector.');
      resultsQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setStarting(false);
    }
  };

  const toggleExperiment = (value) => {
    setForm((current) => ({
      ...current,
      experiments: current.experiments.includes(value)
        ? current.experiments.filter((item) => item !== value)
        : [...current.experiments, value],
    }));
  };

  const result = selected?.result;
  const experiments = result?.experiments || [];
  const metrics = result && !experiments.length ? result : null;

  return (
    <>
      <PageHeading
        eyebrow="Measurement"
        title="Benchmarks"
        subtitle="Generate real load, drive the pipeline, then read metrics back from the index."
        actions={
          <Button icon={Play} size="sm" loading={starting} onClick={run} disabled={selected?.status === 'running'}>
            Run benchmark
          </Button>
        }
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader title="Benchmark configuration" subtitle="Configuration is sent as-is to the collector's measured runner." icon={Gauge} />
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Run name" className="sm:col-span-2">
              <Input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </Field>
            <Field label="Mode">
              <Select value={form.mode} onChange={(event) => setForm({ ...form, mode: event.target.value })}>
                <option value="auto">Auto (gateway if reachable)</option>
                <option value="gateway">Gateway (real HTTP)</option>
                <option value="synthetic">Synthetic (in-process)</option>
              </Select>
            </Field>
            <Field label="Total requests" hint="Capped at 300 when experiments run">
              <Input type="number" min="1" max="5000" value={form.total_requests} onChange={(event) => setForm({ ...form, total_requests: event.target.value })} />
            </Field>
            <Field label="Concurrency">
              <Input type="number" min="1" max="200" value={form.concurrency} onChange={(event) => setForm({ ...form, concurrency: event.target.value })} />
            </Field>
            <Field label="Duration (s)">
              <Input type="number" min="1" max="300" value={form.duration_s} onChange={(event) => setForm({ ...form, duration_s: event.target.value })} />
            </Field>
            <Field label="Error probability (%)">
              <Input type="number" min="0" max="100" value={form.error_probability} onChange={(event) => setForm({ ...form, error_probability: event.target.value })} />
            </Field>
            <Field label="Slow probability (%)">
              <Input type="number" min="0" max="100" value={form.slow_probability} onChange={(event) => setForm({ ...form, slow_probability: event.target.value })} />
            </Field>
            <Field label="Success sampling (%)" hint="Used by the sampling experiment">
              <Input type="number" min="0" max="100" value={form.success_rate} onChange={(event) => setForm({ ...form, success_rate: event.target.value })} />
            </Field>
            <Field label="Batch size" hint="Used by the batching experiment">
              <Input type="number" min="1" value={form.batch_size} onChange={(event) => setForm({ ...form, batch_size: event.target.value })} />
            </Field>
            <Field label="Outage duration (s)">
              <Input type="number" min="0.5" step="0.5" value={form.outage_s} onChange={(event) => setForm({ ...form, outage_s: event.target.value })} />
            </Field>
            <Field label="Concurrency levels" hint="Comma separated, for the sweep">
              <Input value={form.concurrency_levels} onChange={(event) => setForm({ ...form, concurrency_levels: event.target.value })} />
            </Field>
          </div>

          <div className="mt-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted">Comparison experiments</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {EXPERIMENTS.map((experiment) => {
                const active = form.experiments.includes(experiment.value);
                return (
                  <button
                    key={experiment.value}
                    type="button"
                    onClick={() => toggleExperiment(experiment.value)}
                    className={`rounded-btn border px-3 py-1.5 text-[10.5px] font-semibold transition-colors ${
                      active ? 'border-primary bg-blue-50 text-primary' : 'border-line bg-white text-muted hover:text-ink'
                    }`}
                  >
                    {experiment.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-[9.5px] font-medium leading-relaxed text-muted">
              Experiments run each variant sequentially with identical generated traffic and restore live settings afterwards.
              Each variant mutates pipeline settings, so run them one at a time.
            </p>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <Button icon={FlaskConical} loading={starting} onClick={run} disabled={selected?.status === 'running'}>
              {selected?.status === 'running' ? 'Benchmark running…' : 'Start measured run'}
            </Button>
            <span className="text-[10px] font-medium text-muted">
              {formatNumber(form.total_requests)} requests · concurrency {form.concurrency} · {form.duration_s}s cap
            </span>
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="Latest run" subtitle={selected ? selected.name : 'No runs yet'} icon={Timer} action={selected ? <Badge status={selected.status} /> : null} />
          {!selected ? (
            <div className="mt-4">
              <EmptyState title="No benchmark runs" description="Configure and start a run to measure the pipeline." />
            </div>
          ) : (
            <>
              <div className="mt-3 flex items-center justify-between text-[10px] font-medium text-muted">
                <span>Started {formatTime(selected.started_at)}</span>
                <span>{selected.finished_at ? `Finished ${formatTime(selected.finished_at)}` : 'in progress'}</span>
              </div>
              {selected.status === 'running' ? (
                <div className="mt-4 space-y-2">
                  <Skeleton className="h-3 w-full" />
                  <Skeleton className="h-3 w-4/5" />
                  <p className="text-[10px] font-medium text-muted">
                    Load is being generated now. Metrics appear when the runner drains the pipeline and reads back the index.
                  </p>
                </div>
              ) : selected.error ? (
                <p className="mt-3 rounded-widget bg-pink-50 px-3 py-2 text-[10.5px] font-medium text-danger">{selected.error}</p>
              ) : metrics ? (
                <div className="mt-4 space-y-2">
                  {METRIC_TILES.slice(0, 6).map((tile) => (
                    <div key={tile.key} className="flex items-center justify-between rounded-lg bg-canvas px-3 py-2">
                      <span className="text-[10px] font-semibold text-muted">{tile.label}</span>
                      <span className="text-[11px] font-bold text-ink">
                        {metrics[tile.key] === undefined ? '—' : tile.format(metrics[tile.key])}
                      </span>
                    </div>
                  ))}
                </div>
              ) : experiments.length ? (
                <p className="mt-4 text-[10.5px] font-medium text-muted">
                  Comparison run with {experiments.length} experiment(s). Results are shown below.
                </p>
              ) : null}
            </>
          )}
        </Card>
      </div>

      {selected?.status !== 'running' && metrics ? (
        <Card className="mt-4 p-5">
          <CardHeader title="Measured metrics" subtitle={`Mode ${metrics.mode || 'auto'} · read back from PostgreSQL after pipeline drain.`} icon={BarChart3} />
          <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
            {METRIC_TILES.map((tile) => (
              <div key={tile.key} className="rounded-widget border border-line px-3 py-2.5">
                <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{tile.label}</p>
                <p className="mt-0.5 text-[15px] font-extrabold text-ink">
                  {metrics[tile.key] === undefined || metrics[tile.key] === null ? '—' : tile.format(metrics[tile.key])}
                </p>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-4 text-[10px] font-medium text-muted">
            <span>Requested {formatNumber(metrics.requested_requests)}</span>
            <span>Concurrency {metrics.concurrency}</span>
            <span>Error probability {formatPercent((metrics.error_probability || 0) * 100)}</span>
            <span>Indexed delta {formatNumber(metrics.indexed_delta)}</span>
          </div>
        </Card>
      ) : null}

      {experiments.map((experiment) => (
        <Card key={experiment.experiment || experiment.title} className="mt-4 p-5">
          <CardHeader
            title={experiment.title || `${experiment.experiment} comparison`}
            subtitle={experiment.summary || experiment.note || 'Both variants use identical traffic.'}
            icon={FlaskConical}
          />
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <div>
              <VariantChart variants={experiment.variants || []} />
              <p className="mt-1 text-center text-[9.5px] font-medium text-muted">Throughput per variant (spans/s)</p>
            </div>
            <div className="space-y-2">
              {(experiment.variants || []).map((variant) => (
                <div key={variant.label} className="rounded-widget border border-line p-3">
                  <p className="text-[11px] font-bold text-ink">{variant.label}</p>
                  <div className="mt-1.5 grid grid-cols-3 gap-2">
                    {[
                      { label: 'Traces', value: formatNumber(variant.metrics?.traces_stored) },
                      { label: 'Storage', value: formatBytes(variant.metrics?.storage_consumed_bytes) },
                      { label: 'P95', value: formatMs(variant.metrics?.p95_latency_ms) },
                    ].map((item) => (
                      <div key={item.label}>
                        <p className="text-[8.5px] font-bold uppercase tracking-wider text-muted">{item.label}</p>
                        <p className="text-[10.5px] font-bold text-ink">{item.value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {experiment.improvement ? (
                <p className="rounded-widget bg-canvas px-3 py-2 text-[10px] font-medium text-slate-600">
                  {Object.entries(experiment.improvement)
                    .map(([key, value]) => `${key.replaceAll('_', ' ')}: ${value}`)
                    .join(' · ')}
                </p>
              ) : null}
            </div>
          </div>
        </Card>
      ))}

      <Card className="mt-4 p-5">
        <CardHeader title="Run history" subtitle="Persisted benchmark records." icon={Zap} />
        <div className="mt-3">
          {resultsQuery.error ? (
            <ErrorState message={resultsQuery.error} onRetry={resultsQuery.refresh} />
          ) : !results.length ? (
            <EmptyState title="No runs recorded" description="Start a benchmark to create history." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head pb-2 text-left">Run</th>
                    <th className="table-head pb-2 text-left">Status</th>
                    <th className="table-head pb-2 text-left">Mode</th>
                    <th className="table-head pb-2 text-right">Requests</th>
                    <th className="table-head pb-2 text-right">Spans</th>
                    <th className="table-head pb-2 text-right">P95</th>
                    <th className="table-head pb-2 text-right">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((item) => (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedId(item.id)}
                      className={`cursor-pointer border-t border-line transition-colors hover:bg-slate-50/80 ${selected?.id === item.id ? 'bg-blue-50/40' : ''}`}
                    >
                      <td className="py-2.5 text-[11px] font-semibold text-ink">{item.name}</td>
                      <td className="py-2.5"><Badge status={item.status} /></td>
                      <td className="py-2.5 text-[10.5px] font-medium text-muted">{item.config?.mode || '—'}</td>
                      <td className="py-2.5 text-right text-[10.5px] font-semibold text-ink">
                        {formatNumber(item.result?.total_requests_generated ?? item.config?.total_requests)}
                      </td>
                      <td className="py-2.5 text-right text-[10.5px] font-medium text-muted">
                        {formatNumber(item.result?.total_spans_generated)}
                      </td>
                      <td className="py-2.5 text-right text-[10.5px] font-medium text-muted">
                        {item.result?.p95_latency_ms ? formatMs(item.result.p95_latency_ms) : '—'}
                      </td>
                      <td className="py-2.5 text-right text-[10px] font-medium text-muted">{formatTime(item.started_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>
    </>
  );
}
