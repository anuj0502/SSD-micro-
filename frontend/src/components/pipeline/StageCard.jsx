import {
  CloudUpload,
  Database,
  Download,
  Filter,
  GitMerge,
  Layers,
  Package,
} from 'lucide-react';

import { formatMs, formatNumber, statusStyle } from '../../utils/format';

const STAGE_ICONS = {
  ingestion: Download,
  buffer: Layers,
  aggregation: GitMerge,
  sampling: Filter,
  batching: Package,
  storage: CloudUpload,
  indexing: Database,
};

export default function StageCard({ stage, active = false, onClick }) {
  const Icon = STAGE_ICONS[stage.stage] || Layers;
  const tone = statusStyle(stage.health);
  const stats = [
    { label: 'Incoming', value: formatNumber(stage.incoming) },
    { label: 'Processed', value: formatNumber(stage.processed) },
    { label: 'Pending', value: formatNumber(stage.pending) },
    { label: 'Failed', value: formatNumber(stage.failed) },
  ];

  return (
    <button
      type="button"
      onClick={onClick}
      className={`group flex w-full flex-col rounded-widget border bg-white p-3.5 text-left transition-all duration-300 hover:-translate-y-0.5 hover:shadow-lift ${
        active ? 'border-primary shadow-lift' : 'border-line'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-50 text-slate-500">
          <Icon size={15} />
        </span>
        <span className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-wider text-muted">
          <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
          {tone.label}
        </span>
      </div>
      <p className="mt-2.5 text-[11.5px] font-bold leading-tight text-ink">{stage.label}</p>
      <p className="mt-0.5 text-[9.5px] font-medium text-muted">{formatMs(stage.latency_ms)} latency</p>
      <div className="mt-2.5 grid grid-cols-2 gap-x-2 gap-y-1.5 border-t border-line pt-2">
        {stats.map((stat) => (
          <div key={stat.label} className="flex items-baseline justify-between gap-1">
            <span className="text-[8.5px] font-semibold uppercase tracking-wide text-slate-400">{stat.label}</span>
            <span className="text-[10px] font-bold text-ink">{stat.value}</span>
          </div>
        ))}
      </div>
    </button>
  );
}

export function StageConnector({ active = true }) {
  return (
    <div className="hidden w-6 shrink-0 items-center justify-center self-center lg:flex" aria-hidden="true">
      <svg width="24" height="12" viewBox="0 0 24 12" className="overflow-visible">
        <line
          x1="0"
          y1="6"
          x2="18"
          y2="6"
          stroke="#cbd5e1"
          strokeWidth="1.6"
          strokeDasharray="4 4"
          className={active ? 'animate-flow' : ''}
        />
        <path d="M17 2.5 L22 6 L17 9.5" fill="none" stroke="#94a3b8" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
    </div>
  );
}
