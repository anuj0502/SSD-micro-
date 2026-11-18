import { statusStyle } from '../../utils/format';
import { formatMs } from '../../utils/format';

const COLORS = {
  'api-gateway': 'bg-primary',
  'order-service': 'bg-accent',
  'payment-service': 'bg-processing',
  'inventory-service': 'bg-success',
};

export default function Waterfall({ spans = [], selectedSpanId, onSelect }) {
  if (!spans.length) return null;

  const totalMs = Math.max(...spans.map((span) => Number(span.offset_ms) + Number(span.duration_ms)), 1);

  return (
    <div className="min-w-0">
      {/* Axis */}
      <div className="mb-2 flex items-center gap-3 pl-[calc(0px)]">
        <div className="hidden w-[270px] shrink-0 sm:block" />
        <div className="relative flex-1 border-b border-line pb-2">
          <div className="flex justify-between text-[9.5px] font-semibold text-slate-400">
            {[0, 0.25, 0.5, 0.75, 1].map((fraction) => (
              <span key={fraction}>{formatMs(totalMs * fraction)}</span>
            ))}
          </div>
        </div>
        <div className="w-[70px] shrink-0" />
      </div>

      <div className="space-y-0.5">
        {spans.map((span) => {
          const selected = span.span_id === selectedSpanId;
          const tone = statusStyle(span.status === 'ERROR' ? 'error' : 'success');
          const color = COLORS[span.service] || 'bg-slate-400';
          const rowTone = span.status === 'ERROR' ? 'bg-pink-500' : color;
          return (
            <button
              key={span.span_id}
              type="button"
              onClick={() => onSelect?.(span)}
              className={`group flex w-full items-center gap-3 rounded-xl px-1 py-1.5 text-left transition-colors duration-200 ${
                selected ? 'bg-blue-50/70' : 'hover:bg-slate-50'
              }`}
            >
              <div className="flex w-[250px] shrink-0 items-center gap-2 pl-1 sm:w-[270px]">
                <span
                  className="flex min-w-0 items-center gap-2"
                  style={{ paddingLeft: `${Math.min(Number(span.depth || 0), 6) * 14}px` }}
                >
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone.dot}`} />
                  <span className="truncate text-[11.5px] font-bold text-ink">{span.service}</span>
                </span>
              </div>
              <div className="relative flex-1">
                <div className="relative h-7 w-full rounded-md bg-slate-50">
                  <div
                    className={`absolute top-0 h-7 rounded-md ${rowTone} opacity-90 transition-all duration-500 group-hover:opacity-100`}
                    style={{
                      left: `${Math.min(100, Number(span.offset_pct) || 0)}%`,
                      width: `${Math.max(0.6, Number(span.width_pct) || 0.6)}%`,
                    }}
                  >
                    <span className="absolute inset-0 flex items-center truncate px-2 text-[9.5px] font-semibold text-white/95">
                      {span.name}
                    </span>
                  </div>
                </div>
              </div>
              <span className="w-[70px] shrink-0 pr-1 text-right text-[11px] font-bold text-ink">
                {formatMs(span.duration_ms)}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
