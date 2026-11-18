import { useState } from 'react';
import { Activity, AlertTriangle, Clock3, CheckCircle2 } from 'lucide-react';
import useApi from '../../hooks/useApi';
import api from '../../services/api';
import Button from '../ui/Button';
import { useToast } from '../../contexts/ToastContext';

const icons = { 'latency-spike': Clock3, 'payment-failure': AlertTriangle, 'healthy-recovery': CheckCircle2 };
export default function RenderScenarios() {
  const { notify } = useToast();
  const scenariosQuery = useApi(() => api.renderFaultScenarios(), [], { interval: 12000 });
  const runsQuery = useApi(() => api.renderFaultRuns(), [], { interval: 7000 });
  const [busy, setBusy] = useState('');
  const scenarios = scenariosQuery.data?.scenarios || [];
  async function trigger(name) {
    setBusy(name);
    try {
      const run = await api.triggerRenderFault(name);
      notify(run.status === 'completed' ? 'Scenario completed. View its measured results below.' : 'Scenario failed; check the result below.', run.status === 'completed' ? 'success' : 'error');
      runsQuery.refresh();
    } catch (error) { notify(error.message, 'error'); }
    finally { setBusy(''); }
  }
  return <div className="space-y-4">
    <div className="rounded-widget border border-emerald-100 bg-emerald-50 p-4 text-xs text-emerald-900">
      <b>Render application simulation.</b> These scenarios send real instrumented HTTP requests and check recovery. They do not disconnect PostgreSQL, stop workers, or disrupt the collector. Only one experiment can run at a time (8-second cooldown).
    </div>
    <div className="grid gap-4 md:grid-cols-3">
      {scenarios.map(s => { const Icon = icons[s.scenario] || Activity; return <div key={s.scenario} className="rounded-widget border border-line bg-white p-5">
        <Icon size={21} className="text-primary" /><h3 className="mt-3 text-sm font-bold text-ink">{s.title}</h3>
        <p className="mt-2 min-h-12 text-xs text-muted">{s.expected}</p>
        <Button className="mt-3 w-full" size="sm" variant="secondary" disabled={!!busy} loading={busy === s.scenario} onClick={() => trigger(s.scenario)}>Run controlled test</Button>
      </div>; })}
    </div>
    {scenariosQuery.error && <p className="text-xs text-danger">{scenariosQuery.error}</p>}
    <div className="rounded-widget border border-line bg-white p-5">
      <h3 className="text-sm font-bold text-ink">Render fault test history</h3>
      <p className="mt-1 text-xs text-muted">Measured HTTP results are saved to PostgreSQL. New telemetry can take a few seconds to appear in Trace Explorer.</p>
      {!runsQuery.data?.runs?.length ? <p className="mt-4 text-xs text-muted">No application experiments recorded yet.</p> : <div className="mt-3 space-y-2">
        {runsQuery.data.runs.map(run => <div key={run.id} className="rounded-lg border border-line p-3 text-xs">
          <div className="flex items-center justify-between"><b>{run.title}</b><span className={run.status === 'completed' ? 'text-success' : 'text-danger'}>{run.status}</span></div>
          <div className="mt-1 text-muted">Request: HTTP {run.result?.http_status ?? '—'} · {run.result?.request_latency_ms ?? '—'}ms | Recovery: HTTP {run.result?.recovery_http_status ?? '—'} · {run.result?.recovery_latency_ms ?? '—'}ms</div>
        </div>)}
      </div>}
    </div>
  </div>;
}
