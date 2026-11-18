import { Clock3, GitBranch, Tag } from 'lucide-react';

import Badge from '../ui/Badge';
import { formatMs, formatTime, shortId } from '../../utils/format';

export default function SpanDetail({ span }) {
  if (!span) {
    return (
      <div className="rounded-widget border border-dashed border-line bg-canvas/60 px-5 py-8 text-center">
        <p className="text-[12px] font-semibold text-ink">Select a span</p>
        <p className="mt-1 text-[11px] font-medium text-muted">
          Click any bar in the waterfall to inspect its attributes, events and status.
        </p>
      </div>
    );
  }

  const attributes = Object.entries(span.attributes || {});
  const events = span.events || [];

  return (
    <div className="rounded-widget border border-line bg-white">
      <div className="border-b border-line px-4 py-3.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-[13px] font-bold text-ink">{span.name}</p>
            <p className="mt-0.5 text-[11px] font-medium text-muted">{span.service} · {span.kind}</p>
          </div>
          <Badge status={span.status === 'ERROR' ? 'error' : span.status === 'OK' ? 'success' : 'pending'} label={span.status} />
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="rounded-xl bg-canvas px-3 py-2">
            <p className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Duration</p>
            <p className="mt-0.5 text-[13px] font-extrabold text-ink">{formatMs(span.duration_ms)}</p>
          </div>
          <div className="rounded-xl bg-canvas px-3 py-2">
            <p className="text-[9.5px] font-bold uppercase tracking-wider text-muted">Depth</p>
            <p className="mt-0.5 text-[13px] font-extrabold text-ink">{span.depth}</p>
          </div>
        </div>
      </div>

      <div className="space-y-3 px-4 py-4">
        <div className="space-y-1.5 text-[11px]">
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-muted"><Tag size={11} /> Span ID</span>
            <span className="font-mono font-semibold text-ink">{shortId(span.span_id, 10, 4)}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-muted"><GitBranch size={11} /> Parent</span>
            <span className="font-mono font-semibold text-ink">
              {span.parent_span_id ? shortId(span.parent_span_id, 8, 4) : 'root'}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5 text-muted"><Clock3 size={11} /> Started</span>
            <span className="font-semibold text-ink">{formatTime(span.start_time)}</span>
          </div>
        </div>

        {span.status_message ? (
          <p className="rounded-lg bg-pink-50 px-3 py-2 text-[11px] font-medium text-pink-600">{span.status_message}</p>
        ) : null}

        <div>
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Attributes</p>
          {attributes.length === 0 ? (
            <p className="text-[11px] font-medium text-slate-400">No span attributes.</p>
          ) : (
            <div className="panel-scroll max-h-40 space-y-1 overflow-y-auto">
              {attributes.map(([key, value]) => (
                <div key={key} className="flex items-start justify-between gap-3 rounded-md bg-canvas px-2.5 py-1.5">
                  <span className="max-w-[55%] break-all text-[10.5px] font-medium text-muted">{key}</span>
                  <span className="break-all text-right font-mono text-[10.5px] font-semibold text-ink">
                    {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wider text-muted">Events ({events.length})</p>
          {events.length === 0 ? (
            <p className="text-[11px] font-medium text-slate-400">No span events recorded.</p>
          ) : (
            <ul className="space-y-1.5">
              {events.map((event, index) => (
                <li key={`${event.name}-${index}`} className="rounded-md border border-line px-2.5 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[10.5px] font-bold text-ink">{event.name}</span>
                    <span className="text-[9.5px] font-medium text-muted">
                      {event.time_unix_nano ? formatTime(event.time_unix_nano / 1e9) : ''}
                    </span>
                  </div>
                  {Object.keys(event.attributes || {}).length ? (
                    <p className="mt-1 break-all font-mono text-[9.5px] font-medium text-muted">
                      {JSON.stringify(event.attributes)}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
