import { NavLink } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  Boxes,
  Database,
  Filter,
  Gauge,
  LayoutDashboard,
  Network,
  Search,
  Workflow,
  Zap,
  ShoppingCart,
} from 'lucide-react';

import { useApp } from '../../contexts/AppContext';
import { StatusDot } from '../ui/Badge';
import { formatNumber } from '../../utils/format';

export const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/live', label: 'Live Traces', icon: Activity },
  { to: '/traces', label: 'Trace Explorer', icon: Search },
  { to: '/services', label: 'Service Map', icon: Network },
  { to: '/pipeline', label: 'Telemetry Pipeline', icon: Workflow },
  { to: '/sampling', label: 'Sampling Engine', icon: Filter },
  { to: '/storage', label: 'Storage & Indexing', icon: Database },
  { to: '/faults', label: 'Fault Injection', icon: Zap },
  { to: '/benchmarks', label: 'Benchmarks', icon: Gauge },
  { to: '/real-demo', label: 'Real HTTP Demo', icon: ShoppingCart },
];

function ComponentRow({ label, status }) {
  const tone = status === 'healthy' || status === 'running' ? 'healthy' : status === 'starting' ? 'warning' : 'down';
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[11.5px] font-medium text-muted">{label}</span>
      <span className="flex items-center gap-1.5 text-[11px] font-semibold capitalize text-ink">
        <StatusDot status={tone} />
        {status || 'unknown'}
      </span>
    </div>
  );
}

export default function Sidebar({ open = false, onClose }) {
  const { health, services } = useApp();
  const components = health?.components || {};
  const collector = components.collector || {};
  const workerStates = collector.workers || {};
  const runningWorkers = Object.values(workerStates).filter((state) => state === 'running').length;
  const serviceCount = services?.total_services ?? (services?.services ? services.services.length : 0);
  const connected = health?.status === 'ok';

  return (
    <>
      {open ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onClose}
          className="fixed inset-0 z-30 bg-slate-900/30 backdrop-blur-[2px] lg:hidden"
        />
      ) : null}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 shrink-0 flex-col border-r border-line bg-surface transition-transform duration-300 lg:static lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand */}
        <div className="flex items-center gap-3 px-6 pb-5 pt-7">
          <div className="relative h-10 w-10">
            <span className="absolute left-0 top-1 h-8 w-8 rounded-full bg-primary opacity-90" />
            <span className="absolute bottom-1 right-0 h-8 w-8 rounded-full bg-accent opacity-80 mix-blend-multiply" />
            <span className="absolute left-[13px] top-[13px] h-3.5 w-3.5 rounded-full bg-white/90" />
          </div>
          <div>
            <p className="text-[17px] font-extrabold leading-none tracking-tight text-ink">TraceFlow</p>
            <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
              Distributed Observability
            </p>
          </div>
        </div>

        {/* Environment */}
        <div className="px-4">
          <div className="flex items-center justify-between gap-2 rounded-widget bg-[#fff7ed] px-3 py-2.5">
            <div className="flex items-center gap-2">
              <Boxes size={15} className="text-accent" />
              <span className="text-[11.5px] font-bold text-accent">{health?.environment === 'production' ? 'Render Deployment' : 'Local Environment'}</span>
            </div>
            <span className="flex items-center gap-1.5">
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? 'bg-success' : 'bg-danger animate-pulse-soft'}`}
              />
              <span className="text-[9.5px] font-bold uppercase tracking-wider text-accent">
                {connected ? 'Connected' : 'Offline'}
              </span>
            </span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="panel-scroll mt-5 flex-1 overflow-y-auto px-3">
          <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">Workspace</p>
          <ul className="space-y-1">
            {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  onClick={onClose}
                  className={({ isActive }) =>
                    `group flex items-center gap-3 rounded-btn px-3 py-2.5 text-[12.5px] font-semibold transition-all duration-300 ${
                      isActive
                        ? 'bg-blue-50 text-primary shadow-[inset_0_0_0_1px_rgba(13,110,253,0.08)]'
                        : 'text-muted hover:bg-slate-50 hover:text-ink'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={17} className={isActive ? 'text-primary' : 'text-slate-400 group-hover:text-slate-500'} />
                      <span className="truncate">{label}</span>
                      {isActive ? <span className="ml-auto h-1.5 w-1.5 rounded-full bg-primary" /> : null}
                    </>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>

          <p className="mt-6 px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">Reference</p>
          <a
            href="/api/docs"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-3 rounded-btn px-3 py-2.5 text-[12.5px] font-semibold text-muted transition-colors hover:bg-slate-50 hover:text-ink"
          >
            <BarChart3 size={17} className="text-slate-400" />
            API Reference
          </a>
        </nav>

        {/* System health */}
        <div className="px-4 pb-6 pt-2">
          <div className="rounded-widget border border-line bg-canvas/70 p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[11px] font-bold text-ink">System Health</p>
              <span className={`text-[9.5px] font-bold uppercase tracking-wider ${connected ? 'text-success' : 'text-danger'}`}>
                {connected ? 'Operational' : 'Degraded'}
              </span>
            </div>
            <ComponentRow label="Collector" status={collector.status || 'unknown'} />
            <ComponentRow label={components.redis?.backend === "memory" ? "In-memory buffer" : "Redis buffer"} status={components.redis?.status} />
            <ComponentRow label={components.minio?.backend === "postgres" ? "PostgreSQL objects" : "Object storage"} status={components.minio?.status} />
            <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
              <span className="text-[11.5px] font-medium text-muted">Services connected</span>
              <span className="text-[11.5px] font-bold text-ink">{formatNumber(serviceCount)}</span>
            </div>
            <div className="flex items-center justify-between pt-1">
              <span className="text-[11.5px] font-medium text-muted">Active workers</span>
              <span className="text-[11.5px] font-bold text-ink">{runningWorkers}/5</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
