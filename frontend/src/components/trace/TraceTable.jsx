import { useNavigate } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';

import Badge from '../ui/Badge';
import { EmptyState, ErrorState, SkeletonRows } from '../ui/Feedback';
import { formatMs, formatTime, shortId } from '../../utils/format';

export default function TraceTable({
  traces = [],
  loading = false,
  error = null,
  onRetry,
  compact = false,
  emptyTitle = 'No traces found',
  emptyDescription = 'Send traffic through the demo services or run a benchmark to populate the pipeline.',
  showOperation = true,
}) {
  const navigate = useNavigate();

  if (loading && traces.length === 0) return <SkeletonRows rows={5} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (!traces.length) return <EmptyState title={emptyTitle} description={emptyDescription} />;

  const openTrace = (traceId) => navigate(`/traces/${traceId}`);

  return (
    <div className="-mx-1 overflow-x-auto">
      <table className="w-full min-w-[620px] border-collapse">
        <thead>
          <tr className="text-left">
            <th className="table-head pb-2.5 pl-2 pr-3 font-semibold">Trace ID</th>
            <th className="table-head pb-2.5 pr-3 font-semibold">Service</th>
            {showOperation ? <th className="table-head pb-2.5 pr-3 font-semibold">Operation</th> : null}
            <th className="table-head pb-2.5 pr-3 font-semibold">Duration</th>
            <th className="table-head pb-2.5 pr-3 font-semibold">Status</th>
            <th className="table-head pb-2.5 pr-2 text-right font-semibold">Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {traces.map((trace) => (
            <tr
              key={trace.trace_id}
              onClick={() => openTrace(trace.trace_id)}
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter') openTrace(trace.trace_id);
              }}
              className="group cursor-pointer border-t border-line transition-colors duration-200 hover:bg-slate-50/80"
            >
              <td className="py-3 pl-2 pr-3">
                <span className="inline-flex items-center gap-1.5 font-mono text-[11.5px] font-semibold text-ink">
                  {shortId(trace.trace_id, compact ? 8 : 12, 4)}
                  <ArrowUpRight
                    size={11}
                    className="text-slate-300 opacity-0 transition-opacity group-hover:opacity-100"
                  />
                </span>
              </td>
              <td className="py-3 pr-3">
                <span className="rounded-md bg-slate-50 px-2 py-1 text-[11px] font-semibold text-slate-600">
                  {trace.root_service || '—'}
                </span>
              </td>
              {showOperation ? (
                <td className="max-w-[220px] truncate py-3 pr-3 text-[11.5px] font-medium text-muted">
                  {trace.root_operation || '—'}
                </td>
              ) : null}
              <td
                className={`py-3 pr-3 text-[11.5px] font-bold ${
                  trace.status === 'slow' ? 'text-accent' : 'text-ink'
                }`}
              >
                {formatMs(trace.duration_ms)}
              </td>
              <td className="py-3 pr-3">
                <Badge status={trace.status} />
              </td>
              <td className="py-3 pr-2 text-right text-[11px] font-medium text-muted">
                {formatTime(trace.start_time)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
