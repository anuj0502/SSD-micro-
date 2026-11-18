import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowLeft,
  Copy,
  Database,
  GitBranch,
  Info,
  Layers,
  Timer,
  Waypoints,
} from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Waterfall from '../components/trace/Waterfall';
import SpanDetail from '../components/trace/SpanDetail';
import { ErrorState, Skeleton } from '../components/ui/Feedback';
import { useToast } from '../contexts/ToastContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { decisionLabel, formatDateTime, formatMs, formatNumber, shortId } from '../utils/format';

function MetaItem({ label, children, mono = false }) {
  return (
    <div>
      <p className="text-[9.5px] font-bold uppercase tracking-wider text-muted">{label}</p>
      <div className={`mt-1 text-[12px] font-semibold text-ink ${mono ? 'break-all font-mono text-[11px]' : ''}`}>
        {children || '—'}
      </div>
    </div>
  );
}

export default function TraceDetails() {
  const { traceId } = useParams();
  const navigate = useNavigate();
  const { notify } = useToast();
  const query = useApi(() => api.trace(traceId), [traceId]);
  const [selectedSpanId, setSelectedSpanId] = useState(null);

  const trace = query.data;
  const spans = trace?.spans || [];

  useEffect(() => {
    if (spans.length && !spans.some((span) => span.span_id === selectedSpanId)) {
      setSelectedSpanId(spans[0].span_id);
    }
  }, [spans, selectedSpanId]);

  const selectedSpan = spans.find((span) => span.span_id === selectedSpanId) || null;

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(traceId);
      notify('Trace ID copied to clipboard.');
    } catch {
      notify('Clipboard is not available in this browser.', 'error');
    }
  };

  if (query.loading) {
    return (
      <>
        <PageHeading eyebrow="Trace detail" title="Loading trace…" subtitle="Fetching metadata and decompressing the stored batch." />
        <Skeleton className="h-40 rounded-card" />
        <div className="mt-4 grid gap-4 xl:grid-cols-3">
          <Skeleton className="h-[420px] rounded-card xl:col-span-2" />
          <Skeleton className="h-[420px] rounded-card" />
        </div>
      </>
    );
  }

  if (query.error) {
    return (
      <>
        <PageHeading
          eyebrow="Trace detail"
          title="Trace unavailable"
          actions={
            <Button variant="secondary" size="sm" icon={ArrowLeft} onClick={() => navigate('/traces')}>
              Back to explorer
            </Button>
          }
        />
        <ErrorState message={query.error} onRetry={query.refresh} />
      </>
    );
  }

  if (!trace) return null;

  const metadata = [
    { label: 'Trace ID', value: <span className="break-all font-mono text-[11px]">{trace.trace_id}</span> },
    { label: 'Root span', value: trace.root_operation },
    { label: 'Root service', value: trace.root_service },
    { label: 'Total duration', value: formatMs(trace.duration_ms) },
    { label: 'Spans', value: formatNumber(trace.span_count) },
    { label: 'Services involved', value: formatNumber(trace.service_count) },
    { label: 'Started at', value: formatDateTime(trace.start_time) },
    { label: 'Sampling decision', value: decisionLabel(trace.decision_reason) },
    { label: 'Batch object', value: trace.object_key ? <span className="break-all font-mono text-[10px]">{trace.object_key}</span> : 'not yet batched' },
  ];

  return (
    <>
      <PageHeading
        eyebrow="Trace detail"
        title={shortId(trace.trace_id, 18, 6)}
        subtitle={`${trace.root_operation} · ${trace.root_service} · ${formatDateTime(trace.start_time)}`}
        actions={
          <>
            <Button variant="secondary" size="sm" icon={Copy} onClick={copyId}>
              Copy ID
            </Button>
            <Button variant="secondary" size="sm" icon={ArrowLeft} onClick={() => navigate('/traces')}>
              Explorer
            </Button>
          </>
        }
      />

      {trace.warning ? (
        <div className="mb-4 flex items-start gap-2.5 rounded-widget border border-orange-100 bg-orange-50/70 px-4 py-3">
          <Info size={15} className="mt-0.5 shrink-0 text-accent" />
          <p className="text-[11.5px] font-medium leading-relaxed text-orange-700">{trace.warning}</p>
        </div>
      ) : null}

      {trace.has_error ? (
        <div className="mb-4 flex items-start gap-2.5 rounded-widget border border-pink-100 bg-pink-50/70 px-4 py-3">
          <AlertTriangle size={15} className="mt-0.5 shrink-0 text-danger" />
          <div>
            <p className="text-[11.5px] font-bold text-pink-700">This trace contains a failed span</p>
            <p className="mt-0.5 text-[11px] font-medium text-pink-600">
              {trace.error_message || 'The root span reported an error status.'}
            </p>
          </div>
        </div>
      ) : null}

      {/* Metadata */}
      <Card className="p-5">
        <CardHeader
          title="Trace metadata"
          subtitle="Aggregated from span timestamps at aggregation time."
          icon={Waypoints}
          action={
            <div className="flex items-center gap-2">
              <Badge status={trace.status} />
              <span
                className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${
                  trace.sampled ? 'bg-emerald-50 text-success' : 'bg-slate-100 text-muted'
                }`}
              >
                {trace.sampled ? 'Retained' : 'Discarded'}
              </span>
            </div>
          }
        />
        <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4 md:grid-cols-3 xl:grid-cols-5">
          {metadata.map((item) => (
            <MetaItem key={item.label} label={item.label}>
              {item.value}
            </MetaItem>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted">Services</span>
          {(trace.services || []).map((service) => (
            <span
              key={service.service}
              className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[10.5px] font-semibold text-slate-600"
            >
              {service.service}
              <span className="text-[9px] font-bold text-muted">{service.span_count}</span>
            </span>
          ))}
          {!(trace.services || []).length ? <span className="text-[11px] font-medium text-muted">No service metadata.</span> : null}
        </div>
      </Card>

      {/* Waterfall + span panel */}
      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="min-w-0 p-5 xl:col-span-2">
          <CardHeader
            title="Trace waterfall"
            subtitle={
              spans.length
                ? 'Ordered by parent-child relationships; offsets and widths come from real span timestamps.'
                : 'Span bodies are loaded from the compressed batch in object storage.'
            }
            icon={Layers}
            action={
              spans.length ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-muted">
                  <Timer size={11} /> {formatMs(trace.duration_ms)}
                </span>
              ) : null
            }
          />
          <div className="mt-4">
            {spans.length ? (
              <Waterfall spans={spans} selectedSpanId={selectedSpanId} onSelect={(span) => setSelectedSpanId(span.span_id)} />
            ) : (
              <div className="rounded-widget border border-dashed border-line px-5 py-12 text-center">
                <GitBranch size={20} className="mx-auto text-slate-300" />
                <p className="mt-2 text-[12px] font-bold text-ink">No span bodies available</p>
                <p className="mx-auto mt-1 max-w-sm text-[11px] font-medium text-muted">
                  {trace.sampled
                    ? 'The trace is queued for batching. Reload shortly, or check the batch detail on the Storage page.'
                    : 'The tail sampler discarded this trace, so only its metadata was retained.'}
                </p>
              </div>
            )}
          </div>
          {trace.batch_id ? (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-widget bg-canvas/70 px-3.5 py-2.5">
              <span className="inline-flex items-center gap-1.5 text-[10.5px] font-medium text-muted">
                <Database size={12} /> Batch <span className="font-mono font-semibold text-ink">{trace.batch_id}</span>
              </span>
              <button
                type="button"
                onClick={() => navigate('/storage')}
                className="text-[10px] font-bold text-primary hover:text-blue-700"
              >
                Inspect storage
              </button>
            </div>
          ) : null}
        </Card>

        <div>
          <SpanDetail span={selectedSpan} />
        </div>
      </div>
    </>
  );
}
