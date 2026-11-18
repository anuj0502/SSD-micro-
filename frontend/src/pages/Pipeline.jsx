import { useEffect, useState } from 'react';
import { Activity, ArrowRight, CheckCircle2, FlaskConical, GitMerge, Layers, RefreshCw, Workflow } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import StageCard, { StageConnector } from '../components/pipeline/StageCard';
import { ErrorState, Skeleton } from '../components/ui/Feedback';
import { useApp } from '../contexts/AppContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatMs, formatNumber, formatTime } from '../utils/format';

function QueueTile({ label, value, hint, tone = 'blue' }) {
  const tones = {
    blue: 'text-primary bg-blue-50',
    green: 'text-success bg-emerald-50',
    orange: 'text-accent bg-orange-50',
    pink: 'text-danger bg-pink-50',
  };
  return (
    <div className="rounded-widget border border-line bg-white px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-wider text-muted">{label}</span>
        <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-bold ${tones[tone]}`}>live</span>
      </div>
      <p className="mt-1.5 text-[22px] font-extrabold leading-none text-ink">{value}</p>
      <p className="mt-1 text-[9.5px] font-medium text-muted">{hint}</p>
    </div>
  );
}

export default function Pipeline() {
  const { range, refreshTick } = useApp();
  const query = useApi(() => api.pipeline(), [range, refreshTick], { interval: 4000 });
  const [inspected, setInspected] = useState(null);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const [verificationError, setVerificationError] = useState('');

  const startVerification = async () => {
    if (verifying) return;
    setVerification(null);
    setVerificationError('');
    setVerifying(true);
    try {
      const result = await api.startPipelineVerification();
      setVerification({ ...result, state: 'accepted', message: 'Diagnostic span accepted. Waiting for processing and storage.' });
    } catch (error) {
      setVerificationError(error.message || 'Could not start verification');
      setVerifying(false);
    }
  };

  useEffect(() => {
    if (!verifying || !verification?.trace_id) return undefined;
    const traceId = verification.trace_id;
    let active = true;
    let checks = 0;
    const poll = async () => {
      try {
        const result = await api.pipelineVerification(traceId);
        if (!active) return;
        setVerification(result);
        if (result.state === 'stored' || result.state === 'discarded') setVerifying(false);
      } catch (error) {
        if (active) {
          setVerificationError(error.message || 'Verification status could not be loaded');
          setVerifying(false);
        }
      }
      checks += 1;
      if (active && checks >= 30) {
        setVerificationError('Still processing after 90 seconds. Check the trace in Trace Explorer or inspect worker health.');
        setVerifying(false);
      }
    };
    const timer = setInterval(poll, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [verifying, verification?.trace_id]);


  const data = query.data;
  const stages = data?.stages || [];
  const queue = data?.queue || {};
  const workers = data?.workers || {};
  const components = data?.components || {};
  const health = data?.health || 'unknown';
  const backend = data?.deployment?.buffer_backend || 'unknown';

  const stageHistory = inspected ? data?.history?.[inspected.stage] || [] : [];

  return (
    <>
      <PageHeading
        eyebrow="Data path"
        title="Telemetry Pipeline"
        subtitle={`Microservices → Ingestion → ${backend === 'redis' ? 'Redis' : 'In-memory'} Buffer → Aggregation → Sampling → Batching → Storage → Indexing.`}
        actions={
          <>
            <span
              className={`inline-flex h-9 items-center gap-2 rounded-btn border px-3 text-[11px] font-bold ${
                health === 'healthy'
                  ? 'border-emerald-100 bg-emerald-50 text-success'
                  : 'border-orange-100 bg-orange-50 text-accent'
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${health === 'healthy' ? 'bg-success' : 'bg-accent'}`} />
              Pipeline {health}
            </span>
            <Button variant="secondary" size="sm" icon={RefreshCw} onClick={query.refresh}>
              Refresh
            </Button>
          </>
        }
      />

      {query.loading && !data ? (
        <div className="space-y-4">
          <Skeleton className="h-32 rounded-card" />
          <Skeleton className="h-56 rounded-card" />
        </div>
      ) : query.error ? (
        <ErrorState message={query.error} onRetry={query.refresh} />
      ) : (
        <>
          {data?.degraded_stages?.length ? (
            <div className="mb-4 flex items-start gap-2.5 rounded-widget border border-orange-100 bg-orange-50/70 px-4 py-3">
              <Activity size={15} className="mt-0.5 shrink-0 text-accent" />
              <p className="text-[11.5px] font-medium text-orange-700">
                Degraded stages: <span className="font-bold">{data.degraded_stages.join(', ')}</span>. Inspect the stage for
                counters and recent samples.
              </p>
            </div>
          ) : null}

          <div className="mb-4 rounded-widget border border-line bg-white px-4 py-3 text-[11px] text-muted">
            <b className="text-ink">Live processing:</b> {formatNumber(data?.totals?.spans_received)} spans received, {formatNumber(data?.totals?.spans_enqueued)} enqueued and {formatNumber(data?.totals?.traces_indexed)} traces indexed since this process started.
            <span className="block mt-1">A queue depth of <b>0 is normal</b> when workers process incoming spans immediately. Queue counts are current backlog, not historical traffic. Buffer: {backend}. Storage: {data?.deployment?.storage_backend || 'unknown'}.</span>
          </div>
          <Card className="mb-4 p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <span className="rounded-lg bg-blue-50 p-2 text-primary"><FlaskConical size={18} /></span>
                <div>
                  <h3 className="text-sm font-bold text-ink">End-to-end pipeline verification</h3>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted">Send one identifiable diagnostic span through the real ingestion buffer, tail sampling, PostgreSQL index and compressed object storage. The result is checked from persisted data, not a display-only counter.</p>
                </div>
              </div>
              <Button variant="secondary" size="sm" icon={FlaskConical} onClick={startVerification} disabled={verifying}>
                {verifying ? 'Verifying…' : 'Run pipeline test'}
              </Button>
            </div>
            {verification ? (
              <div className="mt-3 rounded-lg border border-line bg-slate-50 p-3 text-[11px] text-muted">
                <div className="flex flex-wrap items-center gap-2">
                  {verification.state === 'stored' ? <CheckCircle2 size={16} className="text-success" /> : <Activity size={16} className="text-primary" />}
                  <span className="font-bold text-ink">{verification.state === 'stored' ? 'Verified: indexed and stored' : verification.state === 'indexed' ? 'Indexed: waiting for batch storage' : verification.state === 'discarded' ? 'Sampling discarded the trace' : 'Accepted: waiting for indexing'}</span>
                </div>
                <p className="mt-1">{verification.message}</p>
                <p className="mt-2 break-all font-mono text-[10px]">Trace ID: {verification.trace_id}</p>
                {verification.indexed ? <a className="mt-2 inline-block font-bold text-primary underline" href={`/traces/${verification.trace_id}`}>Open trace in Trace Explorer</a> : null}
                <p className="mt-1">Ingestion: accepted · PostgreSQL index: {verification.indexed ? 'confirmed' : 'pending'} · Object batch: {verification.stored ? 'confirmed' : 'pending'}</p>
              </div>
            ) : null}
            {verificationError ? <p role="alert" className="mt-3 text-[11px] font-semibold text-danger">{verificationError}</p> : null}
          </Card>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <QueueTile label={backend === 'redis' ? "Stream depth" : "Memory queue depth"} value={formatNumber(queue.stream_depth)} hint="Entries waiting in the buffer" />
            <QueueTile label={backend === 'redis' ? "Pending msgs" : "Unacked messages"} value={formatNumber(queue.pending_messages)} hint="Unacknowledged consumer messages" tone="orange" />
            <QueueTile label="Spill queue" value={formatNumber(queue.spill_depth)} hint="Spans held during buffer outages" tone="pink" />
            <QueueTile label="Batch queue" value={formatNumber(queue.batch_queue)} hint={`${formatNumber(queue.batcher_buffer)} traces in batcher`} tone="green" />
          </div>

          <Card className="mt-4 p-5">
            <CardHeader
              title="Stage flow"
              subtitle="Live cumulative counts and current backlog. Scroll horizontally to see all stages; click a stage for history."
              icon={Workflow}
            />
            <div className="panel-scroll mt-4 overflow-x-auto pb-2">
              <div className="flex w-max min-w-full items-stretch gap-0">
                {stages.map((stage, index) => (
                  <div key={stage.stage} className="flex shrink-0 items-stretch">
                    <div className="w-[190px] shrink-0 sm:w-[200px]">
                      <StageCard stage={stage} active={inspected?.stage === stage.stage} onClick={() => setInspected(stage)} />
                    </div>
                    {index < stages.length - 1 ? <StageConnector active={stage.health === 'healthy'} /> : null}
                  </div>
                ))}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4 border-t border-line pt-3 text-[10px] font-medium text-muted">
              <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-success" /> healthy</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-accent" /> degraded</span>
              <span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-danger" /> down</span>
              <span className="ml-auto">Connectors animate while the upstream stage is healthy.</span>
            </div>
          </Card>

          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <Card className="p-5 xl:col-span-2">
              <CardHeader title="Workers" subtitle="Supervised background tasks inside the collector process." icon={GitMerge} />
              <div className="mt-4 overflow-x-auto">
                <table className="w-full min-w-[520px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head pb-2 text-left">Worker</th>
                      <th className="table-head pb-2 text-left">State</th>
                      <th className="table-head pb-2 text-right">Uptime</th>
                      <th className="table-head pb-2 text-right">Restarts</th>
                      <th className="table-head pb-2 text-right">Last error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(workers).map(([name, worker]) => (
                      <tr key={name} className="border-t border-line">
                        <td className="py-2.5 text-[11.5px] font-semibold capitalize text-ink">{worker.name || name}</td>
                        <td className="py-2.5">
                          <Badge status={worker.running ? 'running' : 'stopped'} />
                        </td>
                        <td className="py-2.5 text-right text-[11px] font-medium text-muted">{formatMs((worker.uptime_s || 0) * 1000)}</td>
                        <td className="py-2.5 text-right text-[11px] font-semibold text-ink">{worker.restarts || 0}</td>
                        <td className="max-w-[220px] truncate py-2.5 text-right text-[10.5px] font-medium text-muted">
                          {worker.last_error || 'none'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <Card className="p-5">
              <CardHeader title="Components" subtitle="Backing infrastructure health." icon={Layers} />
              <div className="mt-4 space-y-2">
                {['collector', 'redis', 'postgres', 'minio'].map((key) => {
                  const component = components[key] || {};
                  return (
                    <div key={key} className="flex items-center justify-between rounded-widget border border-line px-3 py-2.5">
                      <div>
                        <p className="text-[11.5px] font-bold capitalize text-ink">{key === 'minio' ? 'object storage' : key === 'redis' && backend !== 'redis' ? 'memory buffer' : key}</p>
                        <p className="text-[9.5px] font-medium text-muted">
                          {component.backend || component.path || component.url || 'local'}
                        </p>
                      </div>
                      <Badge status={component.status} />
                    </div>
                  );
                })}
              </div>
              <div className="mt-4 rounded-widget bg-canvas/70 px-3.5 py-3">
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted">Flow</p>
                <p className="mt-1 flex flex-wrap items-center gap-1 text-[10px] font-semibold text-ink">
                  Buffer <ArrowRight size={10} /> Aggregate <ArrowRight size={10} /> Sample <ArrowRight size={10} /> Batch
                  <ArrowRight size={10} /> Store <ArrowRight size={10} /> Index
                </p>
              </div>
            </Card>
          </div>
        </>
      )}

      <Modal
        open={Boolean(inspected)}
        onClose={() => setInspected(null)}
        title={inspected?.label || 'Stage'}
        subtitle="Live stage counters and recent persisted samples."
        width="max-w-xl"
      >
        {inspected ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-widget bg-canvas px-4 py-3">
              <span className="text-[11px] font-semibold text-muted">Health</span>
              <Badge status={inspected.health} />
            </div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              {[
                { label: 'Incoming', value: formatNumber(inspected.incoming) },
                { label: 'Processed', value: formatNumber(inspected.processed) },
                { label: 'Pending', value: formatNumber(inspected.pending) },
                { label: 'Failed', value: formatNumber(inspected.failed) },
                { label: 'Latency', value: formatMs(inspected.latency_ms) },
                { label: 'Backlog ratio', value: inspected.incoming ? `${((inspected.pending / Math.max(inspected.incoming, 1)) * 100).toFixed(1)}%` : '0%' },
              ].map((item) => (
                <div key={item.label} className="rounded-xl border border-line px-3 py-2.5">
                  <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{item.label}</p>
                  <p className="mt-0.5 text-[14px] font-extrabold text-ink">{item.value}</p>
                </div>
              ))}
            </div>

            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted">Recent samples</p>
              {stageHistory.length ? (
                <div className="panel-scroll max-h-52 overflow-y-auto rounded-widget border border-line">
                  <table className="w-full border-collapse text-[10.5px]">
                    <thead className="bg-canvas">
                      <tr>
                        <th className="px-3 py-2 text-left font-semibold text-muted">Time</th>
                        <th className="px-3 py-2 text-right font-semibold text-muted">Processed</th>
                        <th className="px-3 py-2 text-right font-semibold text-muted">Pending</th>
                        <th className="px-3 py-2 text-right font-semibold text-muted">Failed</th>
                        <th className="px-3 py-2 text-right font-semibold text-muted">Latency</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...stageHistory].reverse().slice(0, 20).map((sample) => (
                        <tr key={sample.ts} className="border-t border-line">
                          <td className="px-3 py-1.5 font-medium text-muted">{formatTime(sample.ts)}</td>
                          <td className="px-3 py-1.5 text-right font-semibold text-ink">{formatNumber(sample.processed)}</td>
                          <td className="px-3 py-1.5 text-right font-medium text-ink">{formatNumber(sample.pending)}</td>
                          <td className="px-3 py-1.5 text-right font-medium text-ink">{formatNumber(sample.failed)}</td>
                          <td className="px-3 py-1.5 text-right font-medium text-ink">{formatMs(sample.latency_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="rounded-widget border border-dashed border-line px-4 py-6 text-center text-[11px] font-medium text-muted">
                  The metrics worker has not persisted samples for this stage yet.
                </p>
              )}
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
