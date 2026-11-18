import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Archive,
  Box,
  CloudUpload,
  Database,
  FileSearch,
  HardDrive,
  RefreshCw,
  RotateCcw,
  Save,
  Zap,
} from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import StatCard from '../components/ui/StatCard';
import Button from '../components/ui/Button';
import Badge from '../components/ui/Badge';
import Modal from '../components/ui/Modal';
import { Field, Input, Toggle } from '../components/ui/Fields';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback';
import { useToast } from '../contexts/ToastContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import {
  formatBytes,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatTime,
  shortId,
} from '../utils/format';

export default function Storage() {
  const { notify } = useToast();
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [config, setConfig] = useState({ batch_size: 100, flush_interval_s: 5, enabled: true });
  const [saving, setSaving] = useState(false);
  const [flushing, setFlushing] = useState(false);
  const [detailId, setDetailId] = useState(null);
  const [inspectKey, setInspectKey] = useState('');
  const [inspectResult, setInspectResult] = useState(null);
  const [inspecting, setInspecting] = useState(false);

  const statsQuery = useApi(() => api.storageStats(), [], { interval: 6000 });
  const batchQuery = useApi(() => api.batches({ status: status || undefined, page, page_size: 8 }), [status, page], {
    interval: 6000,
  });
  const objectQuery = useApi(() => api.objects(), [], { interval: 15000 });
  const configQuery = useApi(() => api.batchConfig(), []);
  const detailQuery = useApi(() => api.batch(detailId), [detailId], { enabled: Boolean(detailId) });

  useEffect(() => {
    const live = configQuery.data;
    if (live) {
      setConfig({
        batch_size: live.batch_size ?? 100,
        flush_interval_s: live.flush_interval_s ?? 5,
        enabled: live.enabled ?? true,
      });
    }
  }, [configQuery.data]);

  const stats = statsQuery.data || {};
  const batches = batchQuery.data?.items || [];
  const totalPages = batchQuery.data?.pages || 1;
  const objects = objectQuery.data?.objects || [];

  const saveConfig = async () => {
    setSaving(true);
    try {
      await api.updateBatchConfig({
        batch_size: Number(config.batch_size),
        flush_interval_s: Number(config.flush_interval_s),
        enabled: Boolean(config.enabled),
      });
      notify('Batching policy saved and applied to live producer.');
      configQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const flushNow = async () => {
    setFlushing(true);
    try {
      const result = await api.flushBatches();
      notify(`Flushed ${result.batches?.length ?? 0} batch(es) to object storage.`);
      statsQuery.refresh();
      batchQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setFlushing(false);
    }
  };

  const retry = async (batchId) => {
    try {
      await api.retryBatch(batchId);
      notify('Batch re-queued for upload.');
      batchQuery.refresh();
      statsQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    }
  };

  const inspect = async (key) => {
    setInspectKey(key);
    setInspecting(true);
    setInspectResult(null);
    try {
      setInspectResult(await api.inspectObject(key));
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setInspecting(false);
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="Durability"
        title="Storage & Indexing"
        subtitle="Compressed gzip batches in Object Storage, metadata and indexes in PostgreSQL."
        actions={
          <>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={() => { statsQuery.refresh(); batchQuery.refresh(); }}>
              Refresh
            </Button>
            <Button size="sm" icon={Zap} loading={flushing} onClick={flushNow}>
              Flush now
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3.5 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Batches" value={formatNumber(stats.batches)} hint={`${formatNumber(stats.uploaded_batches)} uploaded`} icon={Archive} tone="blue" />
        <StatCard label="Traces stored" value={formatNumber(stats.traces)} hint={`${formatNumber(stats.spans)} spans`} icon={Database} tone="green" />
        <StatCard label="Compressed" value={formatBytes(stats.compressed_bytes)} hint={`${formatBytes(stats.original_bytes)} raw`} icon={Box} tone="orange" />
        <StatCard
          label="Compression"
          value={formatPercent((stats.compression_ratio || 0) * 100)}
          hint="Of uncompressed gzip JSONL size"
          icon={HardDrive}
          tone="purple"
        />
        <StatCard label="Space saved" value={formatBytes(stats.space_saved_bytes)} hint="Versus uncompressed" icon={CloudUpload} tone="green" />
        <StatCard label="PostgreSQL index" value={formatBytes(stats.sqlite_bytes)} hint={`${formatNumber(stats.objects)} objects`} icon={FileSearch} tone="pink" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Batches"
            subtitle="Each row is one gzip JSONL object plus its PostgreSQL metadata."
            icon={Archive}
            action={
              <select
                value={status}
                onChange={(event) => { setStatus(event.target.value); setPage(1); }}
                className="h-8 cursor-pointer rounded-btn border border-line bg-white px-2 text-[10.5px] font-semibold text-ink outline-none"
              >
                <option value="">All statuses</option>
                <option value="uploaded">Uploaded</option>
                <option value="pending">Pending</option>
                <option value="uploading">Uploading</option>
                <option value="failed">Failed</option>
              </select>
            }
          />
          <div className="mt-3">
            {batchQuery.error ? (
              <ErrorState message={batchQuery.error} onRetry={batchQuery.refresh} />
            ) : batchQuery.loading && !batchQuery.data ? (
              <Skeleton className="h-56 w-full" />
            ) : !batches.length ? (
              <EmptyState
                title="No batches yet"
                description="Retained traces are batched by size or flush interval, then uploaded and indexed."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head pb-2 text-left">Batch</th>
                      <th className="table-head pb-2 text-right">Traces</th>
                      <th className="table-head pb-2 text-right">Spans</th>
                      <th className="table-head pb-2 text-right">Size</th>
                      <th className="table-head pb-2 text-right">Ratio</th>
                      <th className="table-head pb-2 text-left">Status</th>
                      <th className="table-head pb-2 text-right">Created</th>
                      <th className="table-head pb-2 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {batches.map((batch) => (
                      <tr
                        key={batch.batch_id}
                        onClick={() => setDetailId(batch.batch_id)}
                        className="cursor-pointer border-t border-line transition-colors hover:bg-slate-50/80"
                      >
                        <td className="py-2.5 font-mono text-[10.5px] font-semibold text-ink">{shortId(batch.batch_id, 12, 3)}</td>
                        <td className="py-2.5 text-right text-[11px] font-semibold text-ink">{formatNumber(batch.trace_count)}</td>
                        <td className="py-2.5 text-right text-[11px] font-medium text-muted">{formatNumber(batch.span_count)}</td>
                        <td className="py-2.5 text-right text-[10.5px] font-medium text-ink">{formatBytes(batch.compressed_bytes)}</td>
                        <td className="py-2.5 text-right text-[10.5px] font-medium text-muted">
                          {formatPercent((batch.compression_ratio || 0) * 100)}
                        </td>
                        <td className="py-2.5"><Badge status={batch.status} /></td>
                        <td className="py-2.5 text-right text-[10px] font-medium text-muted">{formatTime(batch.created_at)}</td>
                        <td className="py-2.5 text-right">
                          {batch.status === 'failed' ? (
                            <button
                              type="button"
                              onClick={(event) => { event.stopPropagation(); retry(batch.batch_id); }}
                              className="inline-flex items-center gap-1 text-[10px] font-bold text-primary hover:text-blue-700"
                            >
                              <RotateCcw size={10} /> Retry
                            </button>
                          ) : (
                            <span className="text-[10px] font-medium text-slate-400">view</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <div className="mt-3 flex items-center justify-between border-t border-line pt-2.5">
              <span className="text-[10px] font-medium text-muted">
                {formatNumber(batchQuery.data?.total)} batches · queue {formatNumber(batchQuery.data?.queue)}
              </span>
              <div className="flex items-center gap-2">
                <button type="button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)} className="text-[10px] font-bold text-primary disabled:opacity-40">Previous</button>
                <span className="text-[10px] font-semibold text-muted">{page} / {totalPages}</span>
                <button type="button" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)} className="text-[10px] font-bold text-primary disabled:opacity-40">Next</button>
              </div>
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="p-5">
            <CardHeader title="Batching policy" subtitle="Live producer configuration." icon={CloudUpload} />
            <div className="mt-4 space-y-3">
              <Field label="Batch size (traces)">
                <Input
                  type="number"
                  min="1"
                  value={config.batch_size}
                  onChange={(event) => setConfig({ ...config, batch_size: event.target.value })}
                />
              </Field>
              <Field label="Flush interval (s)">
                <Input
                  type="number"
                  min="0.2"
                  step="0.1"
                  value={config.flush_interval_s}
                  onChange={(event) => setConfig({ ...config, flush_interval_s: event.target.value })}
                />
              </Field>
              <Toggle
                checked={config.enabled}
                onChange={(value) => setConfig({ ...config, enabled: value })}
                label="Batching enabled"
                description="When off, traces are written one object at a time."
              />
              <Button size="sm" icon={Save} className="w-full" loading={saving} onClick={saveConfig}>
                Save batching policy
              </Button>
            </div>
          </Card>

          <Card className="p-5">
            <CardHeader title="Indexes" subtitle="PostgreSQL query paths used by the API." icon={Database} />
            <div className="mt-3 space-y-1">
              {(stats.indexes || []).map((index) => (
                <p key={index} className="rounded-md bg-canvas px-2.5 py-1.5 font-mono text-[9.5px] font-medium text-slate-600">
                  {index}
                </p>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Object storage"
            subtitle={`${objectQuery.data?.backend || '—'} · ${formatNumber(objectQuery.data?.total)} objects · ${formatBytes(stats.object_bytes)}`}
            icon={Box}
          />
          <div className="mt-3">
            {!objects.length ? (
              <EmptyState title="No objects yet" description="Uploaded batches appear here with their compressed size." />
            ) : (
              <div className="panel-scroll max-h-64 space-y-1 overflow-y-auto">
                {objects.slice(0, 30).map((object) => (
                  <div key={object.key} className="flex items-center justify-between gap-3 rounded-lg px-2.5 py-2 transition-colors hover:bg-slate-50">
                    <span className="min-w-0 truncate font-mono text-[10px] font-medium text-slate-600">{object.key}</span>
                    <div className="flex shrink-0 items-center gap-3">
                      <span className="text-[10px] font-semibold text-ink">{formatBytes(object.size)}</span>
                      <button type="button" onClick={() => inspect(object.key)} className="text-[10px] font-bold text-primary hover:text-blue-700">
                        Inspect
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {stats.object_store_error ? (
              <p className="mt-2 text-[10px] font-medium text-danger">{stats.object_store_error}</p>
            ) : null}
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="Retrieval path" subtitle="How a trace detail request is served." icon={FileSearch} />
          <ol className="mt-3 space-y-2">
            {(stats.retrieval_path || []).map((step) => (
              <li key={step} className="rounded-widget bg-canvas px-3 py-2 text-[10px] font-medium leading-relaxed text-slate-600">
                {step}
              </li>
            ))}
          </ol>
        </Card>
      </div>

      {/* Batch detail */}
      <Modal
        open={Boolean(detailId)}
        onClose={() => setDetailId(null)}
        title={`Batch ${detailId ? shortId(detailId, 16, 4) : ''}`}
        subtitle="Trace metadata indexed for this object."
        width="max-w-2xl"
      >
        {detailQuery.loading ? (
          <Skeleton className="h-40 w-full" />
        ) : detailQuery.error ? (
          <ErrorState compact message={detailQuery.error} onRetry={detailQuery.refresh} />
        ) : detailQuery.data ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { label: 'Status', value: <Badge status={detailQuery.data.status} /> },
                { label: 'Traces', value: formatNumber(detailQuery.data.trace_count) },
                { label: 'Spans', value: formatNumber(detailQuery.data.span_count) },
                { label: 'Size', value: formatBytes(detailQuery.data.compressed_bytes) },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-line px-3 py-2">
                  <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{item.label}</p>
                  <div className="mt-0.5 text-[11.5px] font-bold text-ink">{item.value}</div>
                </div>
              ))}
            </div>
            <p className="break-all rounded-lg bg-canvas px-3 py-2 font-mono text-[10px] text-slate-600">
              {detailQuery.data.object_key}
            </p>
            <div>
              <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Contained traces</p>
              <div className="panel-scroll max-h-64 space-y-1 overflow-y-auto">
                {(detailQuery.data.traces || []).map((trace) => (
                  <button
                    key={trace.trace_id}
                    type="button"
                    onClick={() => { setDetailId(null); navigate(`/traces/${trace.trace_id}`); }}
                    className="flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-slate-50"
                  >
                    <span className="font-mono text-[10px] font-semibold text-ink">{shortId(trace.trace_id, 14, 4)}</span>
                    <span className="text-[10px] font-medium text-muted">{trace.root_service} · {trace.span_count} spans</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

      {/* Object inspection */}
      <Modal
        open={Boolean(inspectKey)}
        onClose={() => { setInspectKey(''); setInspectResult(null); }}
        title="Object inspection"
        subtitle={inspectKey}
        width="max-w-3xl"
      >
        {inspecting ? (
          <Skeleton className="h-48 w-full" />
        ) : inspectResult ? (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div className="rounded-xl border border-line px-3 py-2">
                <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Size</p>
                <p className="mt-0.5 text-[11.5px] font-bold text-ink">{formatBytes(inspectResult.size)}</p>
              </div>
              <div className="rounded-xl border border-line px-3 py-2">
                <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Encoding</p>
                <p className="mt-0.5 text-[11.5px] font-bold text-ink">{inspectResult.encoding || 'gzip'}</p>
              </div>
              <div className="rounded-xl border border-line px-3 py-2">
                <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Lines</p>
                <p className="mt-0.5 text-[11.5px] font-bold text-ink">{formatNumber(inspectResult.line_count)}</p>
              </div>
              <div className="rounded-xl border border-line px-3 py-2">
                <p className="text-[9px] font-bold uppercase tracking-wider text-muted">Modified</p>
                <p className="mt-0.5 text-[11px] font-bold text-ink">{formatDateTime(inspectResult.last_modified)}</p>
              </div>
            </div>
            <pre className="panel-scroll max-h-80 overflow-auto rounded-widget bg-slate-900 p-4 text-[10px] leading-relaxed text-slate-100">
              {JSON.stringify(inspectResult.sample ?? inspectResult.lines ?? inspectResult.preview, null, 2)}
            </pre>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
