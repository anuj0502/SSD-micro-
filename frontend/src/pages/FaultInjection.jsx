import { useState } from 'react';
import { Activity, FlaskConical, History, ShieldAlert, Zap } from 'lucide-react';

import PageHeading from '../components/layout/PageHeading';
import Card, { CardHeader } from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import Modal from '../components/ui/Modal';
import ScenarioCard from '../components/faults/ScenarioCard';
import RenderScenarios from '../components/faults/RenderScenarios';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { EmptyState, ErrorState, Skeleton } from '../components/ui/Feedback';
import { useToast } from '../contexts/ToastContext';
import useApi from '../hooks/useApi';
import api from '../services/api';
import { formatDateTime, formatTime } from '../utils/format';

export default function FaultInjection() {
  const { notify } = useToast();
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(null);
  const [runDetail, setRunDetail] = useState(null);

  const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname);
  const scenariosQuery = useApi(() => isLocal ? api.faultScenarios() : Promise.resolve({scenarios: []}), [isLocal], { interval: 4000 });
  const runsQuery = useApi(() => isLocal ? api.faultRuns({ limit: 12 }) : Promise.resolve({runs: []}), [isLocal], { interval: 4000 });

  const scenarios = scenariosQuery.data?.scenarios || [];
  const runs = runsQuery.data?.runs || [];
  const hasRunning = runs.some((run) => run.status === 'running');

  const trigger = async () => {
    if (!pending) return;
    setBusy(pending.scenario);
    try {
      await api.triggerFault(pending.scenario, {});
      notify(`Scenario "${pending.title}" started. Results appear as the recovery timeline is written.`);
      setPending(null);
      scenariosQuery.refresh();
      runsQuery.refresh();
    } catch (error) {
      notify(error.message, 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeading
        eyebrow="Resilience lab"
        title="Fault Injection"
        subtitle={isLocal ? "Deliberately break the local pipeline and observe recovery." : "Safely demonstrate failures and recovery through measured HTTP requests."}
        actions={
          <div className="flex items-center gap-2">
            <span className="inline-flex h-9 items-center gap-2 rounded-btn border border-orange-100 bg-orange-50 px-3 text-[11px] font-bold text-accent">
              <ShieldAlert size={13} /> {isLocal ? "Local infrastructure lab" : "Render simulation"}
            </span>
            <Button variant="secondary" size="sm" icon={Activity} onClick={() => { scenariosQuery.refresh(); runsQuery.refresh(); }}>
              Refresh
            </Button>
          </div>
        }
      />

      {!isLocal ? <RenderScenarios /> : <>
      <div className="mb-4 rounded-widget border border-line bg-white px-4 py-3.5">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-orange-50 text-accent">
            <FlaskConical size={15} />
          </span>
          <div>
            <p className="text-[12px] font-bold text-ink">Controlled, reversible scenarios</p>
            <p className="mt-0.5 text-[11px] font-medium leading-relaxed text-muted">
              Each scenario mutates live collector state for a bounded time, records an event timeline and verifies
              recovery. Runs execute against this machine's collector, Redis buffer and storage backends — never against
              external systems.
            </p>
          </div>
        </div>
      </div>

      {scenariosQuery.loading && !scenariosQuery.data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-[260px] rounded-card" />
          ))}
        </div>
      ) : scenariosQuery.error ? (
        <ErrorState message={scenariosQuery.error} onRetry={scenariosQuery.refresh} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {scenarios.map((scenario) => (
            <ScenarioCard
              key={scenario.scenario}
              scenario={scenario}
              run={scenario.last_run}
              busy={busy === scenario.scenario}
              onRun={() => setPending(scenario)}
            />
          ))}
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHeader
            title="Run history"
            subtitle="Every trigger is persisted with its recovery timeline."
            icon={History}
            action={hasRunning ? <Badge status="running" label="Run in progress" /> : null}
          />
          <div className="mt-3">
            {runsQuery.error ? (
              <ErrorState message={runsQuery.error} onRetry={runsQuery.refresh} />
            ) : !runs.length ? (
              <EmptyState title="No fault runs yet" description="Trigger a scenario above to record its first run." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse">
                  <thead>
                    <tr>
                      <th className="table-head pb-2 text-left">Scenario</th>
                      <th className="table-head pb-2 text-left">Status</th>
                      <th className="table-head pb-2 text-left">Started</th>
                      <th className="table-head pb-2 text-left">Finished</th>
                      <th className="table-head pb-2 text-right">Events</th>
                      <th className="table-head pb-2 text-right">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.id} className="border-t border-line transition-colors hover:bg-slate-50/80">
                        <td className="py-2.5 text-[11px] font-semibold text-ink">{run.title || run.scenario}</td>
                        <td className="py-2.5"><Badge status={run.status} /></td>
                        <td className="py-2.5 text-[10px] font-medium text-muted">{formatTime(run.started_at)}</td>
                        <td className="py-2.5 text-[10px] font-medium text-muted">
                          {run.finished_at ? formatTime(run.finished_at) : '—'}
                        </td>
                        <td className="py-2.5 text-right text-[10.5px] font-semibold text-ink">
                          {run.timeline?.length || 0}
                        </td>
                        <td className="py-2.5 text-right">
                          <button type="button" onClick={() => setRunDetail(run)} className="text-[10px] font-bold text-primary hover:text-blue-700">
                            Open
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Card>

        <Card className="p-5">
          <CardHeader title="What this proves" subtitle="Scope and limits of the fault lab." icon={Zap} />
          <ul className="mt-3 space-y-2 text-[10.5px] font-medium leading-relaxed text-muted">
            <li className="rounded-widget bg-canvas px-3 py-2">
              <span className="font-bold text-ink">Durability:</span> spans held during Redis loss are spilled to disk and replayed.
            </li>
            <li className="rounded-widget bg-canvas px-3 py-2">
              <span className="font-bold text-ink">Idempotency:</span> duplicate spans are detected by span ID at ingest.
            </li>
            <li className="rounded-widget bg-canvas px-3 py-2">
              <span className="font-bold text-ink">Retries:</span> failed storage uploads back off and recover the same batch.
            </li>
            <li className="rounded-widget bg-canvas px-3 py-2">
              <span className="font-bold text-ink">Integrity:</span> late spans either enrich buffered traces or are dropped per policy.
            </li>
          </ul>
          <p className="mt-3 text-[9.5px] font-medium leading-relaxed text-slate-400">
            Failures are simulated in-process; this is not a chaos-engineering tool for production clusters.
          </p>
        </Card>
      </div>

      </>}
      <ConfirmDialog
        open={Boolean(pending)}
        onClose={() => setPending(null)}
        onConfirm={trigger}
        title={pending ? `Run "${pending.title}"?` : ''}
        description={
          pending
            ? `${pending.expected} The collector will report degraded stages while the scenario runs. Default options are used and recovery is verified automatically.`
            : ''
        }
        confirmLabel="Trigger scenario"
        tone="danger"
        loading={busy === pending?.scenario}
      />

      <Modal
        open={Boolean(runDetail)}
        onClose={() => setRunDetail(null)}
        title={runDetail?.title || 'Fault run'}
        subtitle={runDetail ? `${runDetail.scenario} · started ${formatDateTime(runDetail.started_at)}` : ''}
        width="max-w-2xl"
      >
        {runDetail ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge status={runDetail.status} />
              <span className="text-[10px] font-medium text-muted">{runDetail.expected}</span>
            </div>
            {runDetail.result && Object.keys(runDetail.result).length ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(runDetail.result).map(([key, value]) => (
                  <div key={key} className="rounded-lg border border-line px-3 py-2">
                    <p className="text-[9px] font-bold uppercase tracking-wider text-muted">{key.replaceAll('_', ' ')}</p>
                    <p className="mt-0.5 text-[11px] font-semibold text-ink">
                      {typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}
                    </p>
                  </div>
                ))}
              </div>
            ) : null}
            <div>
              <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted">Timeline</p>
              <ol className="panel-scroll max-h-72 space-y-2 overflow-y-auto border-l border-line pl-3">
                {(runDetail.timeline || []).map((entry, index) => (
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
                    <p className="text-[11px] font-medium text-ink">{entry.message}</p>
                    <p className="text-[9px] font-medium text-slate-400">{formatTime(entry.ts)}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
