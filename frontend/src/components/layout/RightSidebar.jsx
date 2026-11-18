import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronRight, Clock3, ListChecks, Radio, X } from 'lucide-react';

import { useApp } from '../../contexts/AppContext';
import api from '../../services/api';
import useApi from '../../hooks/useApi';
import { timeAgo } from '../../utils/format';
import { StatusDot } from '../ui/Badge';
import { Spinner } from '../ui/Feedback';

function dayKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function buildDays() {
  const today = new Date();
  return Array.from({ length: 7 }).map((_, index) => {
    const date = new Date(today);
    date.setDate(today.getDate() - (6 - index));
    return date;
  });
}

function StatusRow({ label, value, status }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-[11.5px] font-medium text-muted">{label}</span>
      <span className="flex items-center gap-1.5 text-[11px] font-semibold capitalize text-ink">
        <StatusDot status={status} />
        {value || 'unknown'}
      </span>
    </div>
  );
}

export default function RightSidebar({ onClose, drawer = false }) {
  const navigate = useNavigate();
  const { health } = useApp();
  const days = useMemo(buildDays, []);
  const [selectedDay, setSelectedDay] = useState(dayKey(new Date()));

  const eventsQuery = useApi(() => api.events({ limit: 40, hours: 168 }), [], { interval: 15000 });
  const pipelineQuery = useApi(() => api.pipeline(), [], { interval: 10000 });

  const components = health?.components || {};
  const workers = pipelineQuery.data?.workers || {};
  const queue = pipelineQuery.data?.queue || {};
  const events = eventsQuery.data?.items || [];
  const filteredEvents = events.filter((event) => dayKey(new Date(Number(event.ts) * 1000)) === selectedDay);
  const isToday = selectedDay === dayKey(new Date());

  const tasks = [
    {
      label: 'Ingestion worker',
      detail: components.redis?.backend === 'memory' ? 'In-process memory queue' : 'Redis consumer',
      status: workers.ingestion?.running ? 'running' : 'stopped',
    },
    {
      label: 'Processing worker',
      detail: `${queue.stream_depth ?? 0} messages queued`,
      status: workers.processing?.running ? 'running' : 'stopped',
    },
    {
      label: 'Storage worker',
      detail: `${queue.batch_queue ?? 0} batches waiting`,
      status: workers.storage?.running ? 'running' : 'stopped',
    },
    {
      label: 'Spill recovery',
      detail: `${queue.spill_depth ?? 0} spans buffered locally`,
      status: workers.spill?.running ? 'running' : 'stopped',
    },
  ];

  return (
    <aside
      className={
        drawer
          ? 'flex h-full w-[320px] max-w-[88vw] flex-col overflow-y-auto bg-white'
          : 'panel-scroll hidden w-[320px] shrink-0 overflow-y-auto border-l border-line bg-white xl:block'
      }
    >
      <div className="flex items-center justify-between px-5 pb-2 pt-6">
        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">System</p>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-50 hover:text-ink"
            aria-label="Close activity panel"
          >
            <X size={16} />
          </button>
        ) : (
          <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-success">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-success" /> Live
          </span>
        )}
      </div>

      {/* Section 1: system status */}
      <section className="px-4 pt-2">
        <div className="rounded-widget border border-line bg-canvas/60 p-4">
          <StatusRow label="Collector" value={components.collector?.status} status={components.collector?.status} />
          <StatusRow label={components.redis?.backend === "memory" ? "Memory buffer" : "Redis connection"} value={components.redis?.status} status={components.redis?.status} />
          <StatusRow label="PostgreSQL" value={components.postgres?.status} status={components.postgres?.status} />
          <StatusRow label={components.minio?.backend === "postgres" ? "PostgreSQL objects" : "Object Storage / objects"} value={components.minio?.status} status={components.minio?.status} />
          <div className="mt-1 flex items-center justify-between border-t border-line pt-2">
            <span className="text-[11.5px] font-medium text-muted">Active workers</span>
            <span className="text-[11px] font-bold text-ink">
              {Object.values(workers).filter((worker) => worker.running).length}/{Math.max(Object.keys(workers).length, 1)}
            </span>
          </div>
        </div>
      </section>

      {/* Section 2: activity calendar */}
      <section className="px-4 pt-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">Activity Calendar</p>
          <Clock3 size={13} className="text-slate-400" />
        </div>
        <div className="flex items-center justify-between gap-1 rounded-widget border border-line bg-white p-2">
          {days.map((date) => {
            const key = dayKey(date);
            const active = key === selectedDay;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setSelectedDay(key)}
                className={`flex h-12 flex-1 flex-col items-center justify-center rounded-xl transition-all duration-300 ${
                  active ? 'bg-danger text-white shadow-[0_8px_18px_-10px_rgba(236,72,153,0.9)]' : 'text-muted hover:bg-slate-50'
                }`}
                aria-pressed={active}
              >
                <span className="text-[9px] font-bold uppercase tracking-wider opacity-80">
                  {date.toLocaleDateString('en-US', { weekday: 'short' })}
                </span>
                <span className="text-[13px] font-extrabold">{date.getDate()}</span>
              </button>
            );
          })}
        </div>
      </section>

      {/* Section 3: recent activity */}
      <section className="px-4 pt-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">Recent Activity</p>
          <span className="text-[10px] font-semibold text-slate-400">
            {isToday ? 'today' : new Date(`${selectedDay}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
        </div>
        <div className="rounded-widget border border-line bg-white">
          {eventsQuery.loading ? (
            <div className="px-4 py-4">
              <Spinner label="Loading activity" />
            </div>
          ) : eventsQuery.error ? (
            <p className="px-4 py-4 text-[11px] font-medium text-muted">{eventsQuery.error}</p>
          ) : filteredEvents.length === 0 ? (
            <p className="px-4 py-5 text-[11px] font-medium text-muted">No events recorded for this day.</p>
          ) : (
            <ul className="panel-scroll max-h-[240px] divide-y divide-line overflow-y-auto">
              {filteredEvents.slice(0, 8).map((event) => (
                <li key={event.id} className="flex items-start gap-2.5 px-3.5 py-3">
                  <span className="mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-md bg-slate-50">
                    <Radio size={10} className="text-slate-400" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[11.5px] font-semibold leading-snug text-ink">{event.message}</p>
                    <p className="mt-0.5 text-[10px] font-medium text-muted">
                      {timeAgo(event.ts)} · {event.category}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <button
            type="button"
            onClick={() => navigate('/live')}
            className="flex w-full items-center justify-center gap-1 border-t border-line py-2.5 text-[11px] font-bold text-primary transition-colors hover:bg-blue-50/50"
          >
            View live stream <ChevronRight size={12} />
          </button>
        </div>
      </section>

      {/* Section 4: processing tasks */}
      <section className="px-4 pb-6 pt-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted">Processing Tasks</p>
          <ListChecks size={13} className="text-slate-400" />
        </div>
        <div className="space-y-1.5">
          {tasks.map((task) => (
            <div
              key={task.label}
              className="flex items-center justify-between gap-3 rounded-widget border border-line bg-white px-3.5 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate text-[11.5px] font-semibold text-ink">{task.label}</p>
                <p className="truncate text-[10px] font-medium text-muted">{task.detail}</p>
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wide ${
                  task.status === 'running' ? 'bg-emerald-50 text-success' : 'bg-pink-50 text-danger'
                }`}
              >
                {task.status}
              </span>
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
