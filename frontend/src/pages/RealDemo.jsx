import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ShoppingCart, CheckCircle2, AlertTriangle, Clock3 } from 'lucide-react';
import PageHeading from '../components/layout/PageHeading';

const scenarios = [
  { id: 'success', label: 'Successful checkout', hint: 'Actual HTTP request, order confirmed', icon: CheckCircle2 },
  { id: 'slow', label: 'Slow checkout', hint: 'Actual timed delay, recorded in latency', icon: Clock3 },
  { id: 'error', label: 'Failed payment', hint: 'Actual HTTP 503 response and error span', icon: AlertTriangle },
];

export default function RealDemo() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  async function run(scenario) {
    setBusy(true);
    setResult(null);
    try {
      const started = performance.now();
      const response = await fetch(`/demo-app/checkout?scenario=${scenario}`, { method: 'POST' });
      const payload = await response.json();
      setResult({ http: response.status, duration: Math.round(performance.now() - started), payload, scenario });
    } catch (error) {
      setResult({ http: 0, payload: { detail: error.message }, scenario });
    } finally { setBusy(false); }
  }

  return (
    <div className="space-y-6">
      <PageHeading eyebrow="Instrumentation demonstration" title="Real HTTP Demo" subtitle="Generate genuine API traffic through an instrumented FastAPI checkout application. These are measured requests, not synthetic trace records." />
      <div className="rounded-widget border border-line bg-surface p-5 space-y-3">
        <div className="flex items-center gap-2 text-sm font-bold text-ink"><ShoppingCart size={19} /> Live checkout API</div>
        <p className="text-sm text-muted">Each click sends an actual POST request to /demo-app/checkout. OpenTelemetry measures the handler and its operations, exports OTLP to the collector, then TraceFlow indexes the trace into PostgreSQL. This is one instrumented application, not four separately deployed microservices.</p>
        <div className="grid gap-3 md:grid-cols-3">
          {scenarios.map((scenario) => {
            const Icon = scenario.icon;
            return <button key={scenario.id} type="button" disabled={busy} onClick={() => run(scenario.id)} className="rounded-xl border border-line bg-canvas p-4 text-left hover:border-blue-400 disabled:opacity-50 transition-colors">
              <Icon size={21} className="mb-3 text-blue-600" />
              <div className="text-sm font-bold text-ink">{scenario.label}</div><div className="mt-1 text-xs text-muted">{scenario.hint}</div>
            </button>;
          })}
        </div>
      </div>
      {result && <div className="rounded-widget border border-line bg-surface p-5 space-y-3">
        <div className="font-bold text-ink">Request result · HTTP {result.http || 'network error'} {result.duration != null ? `· ${result.duration}ms` : ''}</div>
        <pre className="rounded-lg bg-slate-900 p-4 text-xs text-slate-100 overflow-x-auto whitespace-pre-wrap">{JSON.stringify(result.payload, null, 2)}</pre>
        {result.payload?.trace_id ? <Link className="text-sm font-bold text-blue-600 underline" to={`/traces/${result.payload.trace_id}`}>Inspect the recorded trace (after a few seconds)</Link> : null}
        <p className="text-xs text-muted">Trace export, assembly and tail sampling are asynchronous. A successful request may be discarded by the sampling engine; error/slow scenarios are retained under default sampling rules.</p>
      </div>}
      <div className="rounded-widget border border-line bg-surface p-4 text-xs text-muted">Demo source: real-checkout-api · Trace resource: telemetry.source=real-http-request · Synthetic background traffic remains labeled separately. Avoid sending personal information into this public test endpoint.</div>
    </div>
  );
}
