import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  CheckCircle2,
  Filter,
  RotateCcw,
  Save,
  SlidersHorizontal,
  Timer,
  TrendingDown,
} from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import StatCard from '../components/ui/StatCard';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback';
import { Field, Input, Select, Toggle } from '../components/ui/Fields';
import { useToast } from '../contexts/ToastContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import {
  decisionLabel,
  formatBytes,
  formatMs,
  formatNumber,
  formatPercent,
  formatTime,
  shortId,
} from '../utils/format';

const EMPTY_FORM = {
  errorRate: 100,
  slowThreshold: 500,
  successRate: 10,
  timeout: 5,
  latePolicy: 'drop',
  deterministic: true,
};

export default function Sampling() {
  const { notify } = useToast();
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  const statsQuery = useApi(() => api.samplingStats(), [], { interval: 5000 });
  const configQuery = useApi(() => api.samplingConfig(), []);

  useEffect(() => {
    const config = configQuery.data?.config;
    if (!config) return;
    setForm({
      errorRate: Math.round(config.error_rate * 100),
      slowThreshold: config.slow_threshold_ms,
      successRate: Math.round(config.success_rate * 100),
      timeout: config.completion_timeout_s,
      latePolicy: config.late_policy,
      deterministic: Boolean(config.deterministic),
    });
  }, [configQuery.data]);

  const stats = statsQuery.data?.stats || {};
  const storage = statsQuery.data?.storage || {};
  const persisted = statsQuery.data?.persisted || {};
  const decisions = statsQuery.data?.recent_decisions || [];

  const savePolicy = async () => {
    setSaving(true);
    try {
      await api.updateSamplingConfig({
        error_rate: Number(form.errorRate) / 100,
        slow_threshold_ms: Number(form.slowThreshold),
        success_rate: Number(form.successRate) / 100,
        completion_timeout_s: Number(form.timeout),
        late_policy: form.latePolicy,
        deterministic: Boolean(form.deterministic),
      });
      notify('Sampling policy updated. New decisions apply to traces completed after this change.');
      configQuery.refresh();
      statsQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const resetStats = async () => {
    setResetting(true);
    try {
      await api.resetSamplingStats();
      notify('Sampling counters reset.');
      statsQuery.refresh();
      setConfirmReset(false);
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setResetting(false);
    }
  };

  const withoutSampling = Number(storage.estimated_bytes_without_sampling || 0);
  const storedBytes = Number(storage.compressed_bytes || 0);
  const barWidth = withoutSampling > 0 ? Math.min(100, (storedBytes / withoutSampling) * 100) : 0;

  return (
    <>
      <PageHeading
        eyebrow="Core engine"
        title="Sampling Engine"
        subtitle="Tail-based sampling decisions made after the trace completion window closes."
        actions={
          <>
            <Button variant="secondary" size="sm" icon={RotateCcw} onClick={() => setConfirmReset(true)}>
              Reset stats
            </Button>
            <Button size="sm" icon={Save} loading={saving} onClick={savePolicy}>
              Save policy
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-4 xl:grid-cols-7">
        <StatCard label="Evaluated" value={formatNumber(stats.evaluated)} hint="Completed traces" icon={Filter} tone="blue" />
        <StatCard label="Retained" value={formatNumber(stats.retained)} hint={formatPercent(stats.retention_rate)} icon={CheckCircle2} tone="green" />
        <StatCard label="Discarded" value={formatNumber(stats.discarded)} hint={formatPercent(stats.reduction_rate)} icon={TrendingDown} tone="purple" />
        <StatCard label="Error retained" value={formatNumber(stats.error_retained)} hint={`${formatNumber(stats.error_total)} error traces`} icon={AlertTriangle} tone="pink" />
        <StatCard label="Slow retained" value={formatNumber(stats.slow_retained)} hint={`${formatNumber(stats.slow_total)} above threshold`} icon={Timer} tone="orange" />
        <StatCard label="Success sampled" value={formatNumber(stats.success_sampled)} hint={`${formatNumber(stats.success_total)} successful`} icon={CheckCircle2} tone="blue" />
        <StatCard
          label="Storage reduction"
          value={formatPercent(stats.estimated_storage_reduction)}
          hint="Estimated by trace volume"
          icon={TrendingDown}
          tone="green"
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Policy editor"
            subtitle={configQuery.data?.policy || 'Changes are persisted and applied to live traffic.'}
            icon={SlidersHorizontal}
          />
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Error retention (%)" hint="Percentage of error traces retained">
              <Input
                type="number"
                min="0"
                max="100"
                value={form.errorRate}
                onChange={(event) => setForm({ ...form, errorRate: event.target.value })}
              />
            </Field>
            <Field label="Slow threshold (ms)" hint="Traces at or above this are always kept">
              <Input
                type="number"
                min="0"
                value={form.slowThreshold}
                onChange={(event) => setForm({ ...form, slowThreshold: event.target.value })}
              />
            </Field>
            <Field label="Successful sampling (%)" hint="Deterministic hash sampling by trace ID">
              <Input
                type="number"
                min="0"
                max="100"
                value={form.successRate}
                onChange={(event) => setForm({ ...form, successRate: event.target.value })}
              />
            </Field>
            <Field label="Completion timeout (s)" hint="Inactivity window before the decision">
              <Input
                type="number"
                min="0.1"
                max="300"
                step="0.1"
                value={form.timeout}
                onChange={(event) => setForm({ ...form, timeout: event.target.value })}
              />
            </Field>
            <Field label="Late-arrival policy" hint="Applied to spans arriving after the decision">
              <Select
                value={form.latePolicy}
                onChange={(event) => setForm({ ...form, latePolicy: event.target.value })}
              >
                <option value="drop">Drop late spans</option>
                <option value="accept_if_buffered">Accept if trace still buffered</option>
              </Select>
            </Field>
            <div className="flex items-end pb-2">
              <Toggle
                checked={form.deterministic}
                onChange={(value) => setForm({ ...form, deterministic: value })}
                label="Deterministic sampling"
                description="Stable hash per trace ID for repeatable tests"
              />
            </div>
          </div>

          <div className="mt-4 rounded-widget bg-canvas/70 px-4 py-3">
            <p className="text-[10px] font-bold uppercase tracking-wider text-muted">Decision algorithm</p>
            <ol className="mt-2 grid gap-1.5 text-[10.5px] font-medium text-muted sm:grid-cols-2">
              <li>1. Group spans by trace ID in the assembler.</li>
              <li>2. Wait for inactivity / completion timeout.</li>
              <li>3. Error trace → apply error retention rate.</li>
              <li>4. Duration ≥ threshold → always retain.</li>
              <li>5. Otherwise hash(trace ID) &lt; success rate.</li>
              <li>6. Index metadata; enqueue retained spans for batching.</li>
            </ol>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <Badge status="running" label={`${formatNumber(persisted.evaluated)} persisted evaluations`} />
            <span className="text-[10px] font-medium text-muted">
              late policy {configQuery.data?.config?.late_policy} ·{' '}
              {configQuery.data?.config?.deterministic ? 'deterministic' : 'random'} sampling
            </span>
            <button
              type="button"
              onClick={savePolicy}
              className="ml-auto text-[10px] font-bold text-primary hover:text-blue-700"
            >
              Apply changes
            </button>
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader
            title="Sampling impact"
            subtitle="Enabled vs disabled comparison from stored batches."
            icon={TrendingDown}
          />
          {statsQuery.loading && !statsQuery.data ? (
            <Skeleton className="mt-4 h-40 w-full" />
          ) : (
            <>
              <div className="mt-5 space-y-4">
                <div>
                  <div className="flex items-center justify-between text-[10px] font-semibold text-muted">
                    <span>Sampling disabled (estimate)</span>
                    <span className="text-ink">{formatBytes(withoutSampling)}</span>
                  </div>
                  <div className="mt-1.5 h-3 w-full overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full w-full rounded-full bg-slate-300" />
                  </div>
                </div>
                <div>
                  <div className="flex items-center justify-between text-[10px] font-semibold text-muted">
                    <span>Sampling enabled (actual)</span>
                    <span className="text-ink">{formatBytes(storedBytes)}</span>
                  </div>
                  <div className="mt-1.5 h-3 w-full overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-primary transition-all duration-500"
                      style={{ width: `${Math.max(2, barWidth)}%` }}
                    />
                  </div>
                </div>
              </div>

              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-emerald-50/60 px-3 py-2.5">
                  <p className="text-[9px] font-bold uppercase tracking-wider text-emerald-600">Reduction</p>
                  <p className="mt-0.5 text-[16px] font-extrabold text-success">{formatPercent(storage.reduction_pct)}</p>
                </div>
                <div className="rounded-xl bg-blue-50/60 px-3 py-2.5">
                  <p className="text-[9px] font-bold uppercase tracking-wider text-blue-600">Bytes saved</p>
                  <p className="mt-0.5 text-[16px] font-extrabold text-primary">{formatBytes(storage.estimated_bytes_saved)}</p>
                </div>
              </div>

              <p className="mt-3 text-[9.5px] font-medium leading-relaxed text-muted">
                Disabled cost is derived from {formatNumber(persisted.evaluated)} evaluated traces ×{' '}
                {formatBytes(storage.avg_bytes_per_trace)} average compressed bytes per stored trace. It is an estimate,
                not a second measured run.
              </p>
              <button
                type="button"
                onClick={() => navigate('/benchmarks')}
                className="mt-3 text-[10px] font-bold text-primary hover:text-blue-700"
              >
                Run a measured comparison →
              </button>
            </>
          )}
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <CardHeader
          title="Recent sampling decisions"
          subtitle="Most recent completed traces and why they were kept or dropped."
          icon={Filter}
          action={
            <span className="rounded-full bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-muted">
              {formatNumber(stats.evaluated)} evaluated
            </span>
          }
        />
        <div className="mt-3">
          {statsQuery.error ? (
            <ErrorState message={statsQuery.error} onRetry={statsQuery.refresh} />
          ) : decisions.length === 0 ? (
            <EmptyState
              title="No decisions yet"
              description="Completed traces appear here after the sampling completion window closes."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse">
                <thead>
                  <tr>
                    <th className="table-head pb-2 text-left">Trace</th>
                    <th className="table-head pb-2 text-left">Service</th>
                    <th className="table-head pb-2 text-left">Operation</th>
                    <th className="table-head pb-2 text-right">Duration</th>
                    <th className="table-head pb-2 text-right">Score</th>
                    <th className="table-head pb-2 text-left">Decision</th>
                    <th className="table-head pb-2 text-right">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.slice(0, 10).map((decision) => (
                    <tr
                      key={`${decision.trace_id}-${decision.ts}`}
                      onClick={() => navigate(`/traces/${decision.trace_id}`)}
                      className="cursor-pointer border-t border-line transition-colors hover:bg-slate-50/80"
                    >
                      <td className="py-2.5 font-mono text-[10.5px] font-semibold text-ink">
                        {shortId(decision.trace_id, 12, 4)}
                      </td>
                      <td className="py-2.5 text-[11px] font-medium text-ink">{decision.service}</td>
                      <td className="max-w-[200px] truncate py-2.5 text-[11px] font-medium text-muted">
                        {decision.operation}
                      </td>
                      <td className="py-2.5 text-right text-[11px] font-semibold text-ink">{formatMs(decision.duration_ms)}</td>
                      <td className="py-2.5 text-right font-mono text-[10.5px] font-medium text-muted">
                        {Number(decision.score).toFixed(3)}
                      </td>
                      <td className="py-2.5">
                        <span
                          className={`rounded-full px-2 py-1 text-[9.5px] font-bold ${
                            decision.retained ? 'bg-emerald-50 text-success' : 'bg-slate-100 text-muted'
                          }`}
                        >
                          {decision.retained ? decisionLabel(decision.reason) : 'Discarded'}
                        </span>
                      </td>
                      <td className="py-2.5 text-right text-[10px] font-medium text-muted">{formatTime(decision.ts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Card>

      <ConfirmDialog
        open={confirmReset}
        onClose={() => setConfirmReset(false)}
        onConfirm={resetStats}
        title="Reset sampling counters?"
        description="This clears in-memory decision statistics and the recent decision list. Stored traces, batches and persisted metadata are not affected."
        confirmLabel="Reset counters"
        tone="danger"
        loading={resetting}
      />
    </>
  );
}
