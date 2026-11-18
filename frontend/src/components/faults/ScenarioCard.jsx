import { useState } from 'react';
import { ChevronDown, ChevronUp, Play, ShieldCheck, TriangleAlert } from 'lucide-react';

import Card from '../ui/Card';
import Badge from '../ui/Badge';
import Button from '../ui/Button';
import { formatDateTime, formatNumber, timeAgo } from '../../utils/format';

const RESULT_LABELS = {
  spans_emitted: 'Spans emitted',
  messages_delivered_without_ack: 'Delivered without ACK',
  pending_at_crash: 'Pending at crash',
  pending_after_recovery: 'Pending after recovery',
  duplicates_suppressed: 'Duplicates suppressed',
  spans_persisted_delta: 'Spans persisted',
  recovery_time_ms: 'Recovery time (ms)',
  worker_restarts: 'Worker restarts',
  duplicate_persistence: 'Duplicate persistence',
  buffer_backend: 'Buffer backend',
  buffer_unavailable_events: 'Unavailable events',
  spans_spilled: 'Spans spilled',
  spans_rejected: 'Spans rejected',
  spill_queue_depth_at_peak: 'Spill queue peak',
  spill_queue_drained: 'Spill queue drained',
  spill_flushed: 'Spans flushed from spill',
  batches_failed: 'Batches failed',
  batches_recovered: 'Batches recovered',
  attempts_until_success: 'Attempts until success',
  max_backoff_ms: 'Max backoff (ms)',
  queue_depth_peak: 'Queue depth peak',
  accepted_during_burst: 'Accepted during burst',
  backpressure_events: 'Backpressure events',
  drain_time_ms: 'Drain time (ms)',
  duplicate_spans_sent: 'Duplicate spans sent',
  duplicates_detected: 'Duplicates detected',
  duplicates_persisted: 'Duplicates persisted',
  dedup_ratio: 'Dedup ratio',
  late_spans_sent: 'Late spans sent',
  late_spans_applied: 'Late spans applied',
  late_spans_dropped: 'Late spans dropped',
  late_policy: 'Late policy',
  trace_integrity_ok: 'Trace integrity preserved',
};

function renderValue(value) {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'number') return formatNumber(value, 2);
  if (value === null || value === undefined) return '—';
  return String(value);
}

export default function ScenarioCard({ scenario, run, onRun, busy = false }) {
  const [showTimeline, setShowTimeline] = useState(false);
  const status = run?.status || 'idle';
  const result = run?.result || {};
  const entries = Object.entries(result).filter(([key]) => key in RESULT_LABELS);
  const recovered =
    run &&
    run.status === 'completed' &&
    (result.pending_after_recovery === 0 ||
      result.spill_queue_drained === true ||
      result.batches_recovered > 0 ||
      result.duplicate_persistence === false ||
      result.trace_integrity_ok === true ||
      !('pending_after_recovery' in result));

  return (
    <Card hover className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[14.5px] font-bold text-ink">{scenario.title}</h3>
          <p className="mt-1 text-[11px] font-medium leading-relaxed text-muted">{scenario.expected}</p>
        </div>
        <Badge status={status === 'idle' ? 'pending' : status} label={status === 'idle' ? 'Idle' : status} />
      </div>

      {run ? (
        <div className="mt-3 space-y-2.5">
          <div className="rounded-widget bg-canvas/70 px-3 py-2.5">
            <div className="flex items-center justify-between text-[10px] font-semibold text-muted">
              <span>Actual behavior</span>
              <span>{timeAgo(run.started_at)}</span>
            </div>
            {entries.length ? (
              <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1">
                {entries.slice(0, 8).map(([key, value]) => (
                  <div key={key} className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[9.5px] font-medium text-muted">{RESULT_LABELS[key]}</span>
                    <span className="shrink-0 text-[10px] font-bold text-ink">{renderValue(value)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1.5 text-[10.5px] font-medium text-muted">
                {run.status === 'running' ? 'Scenario running — results appear when it finishes.' : 'No metrics recorded.'}
              </p>
            )}
          </div>

          <div className="flex items-center justify-between rounded-widget border border-line px-3 py-2">
            <span className="flex items-center gap-1.5 text-[10.5px] font-semibold text-muted">
              {recovered ? <ShieldCheck size={13} className="text-success" /> : <TriangleAlert size={13} className="text-accent" />}
              Recovery
            </span>
            <span className={`text-[10px] font-bold ${recovered ? 'text-success' : 'text-accent'}`}>
              {recovered ? 'Verified' : run.status === 'running' ? 'In progress' : 'Unconfirmed'}
            </span>
          </div>

          {run.timeline?.length ? (
            <div>
              <button
                type="button"
                onClick={() => setShowTimeline((value) => !value)}
                className="flex w-full items-center justify-between rounded-lg px-1 py-1 text-[10px] font-bold uppercase tracking-wider text-muted transition-colors hover:text-ink"
              >
                Event timeline ({run.timeline.length})
                {showTimeline ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
              {showTimeline ? (
                <ol className="panel-scroll mt-1 max-h-44 space-y-2 overflow-y-auto border-l border-line pl-3">
                  {run.timeline.map((entry, index) => (
                    <li key={`${entry.ts}-${index}`} className="relative">
                      <span
                        className={`absolute -left-[17px] top-1 h-1.5 w-1.5 rounded-full ${
                          entry.status === 'error'
                            ? 'bg-danger'
                            : entry.status === 'warning'
                              ? 'bg-accent'
                              : entry.status === 'success'
                                ? 'bg-success'
                                : 'bg-slate-300'
                        }`}
                      />
                      <p className="text-[10.5px] font-medium leading-snug text-ink">{entry.message}</p>
                      <p className="text-[9px] font-medium text-slate-400">{formatDateTime(entry.ts).split(', ')[1]}</p>
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-3 rounded-widget border border-dashed border-line px-3 py-4 text-center">
          <p className="text-[10.5px] font-medium text-muted">Not run yet. Trigger the scenario to observe real recovery behavior.</p>
        </div>
      )}

      <div className="mt-auto pt-3">
        <Button
          size="sm"
          variant="secondary"
          icon={Play}
          className="w-full"
          loading={busy || status === 'running'}
          disabled={run && run.status === 'running'}
          onClick={() => onRun(scenario.scenario)}
        >
          {run && run.status === 'running' ? 'Running scenario…' : 'Trigger scenario'}
        </Button>
      </div>
    </Card>
  );
}
