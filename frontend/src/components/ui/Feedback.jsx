import { AlertCircle, Inbox, RefreshCw } from 'lucide-react';
import Button from './Button';

export function Skeleton({ className = '' }) {
  return <div className={`skeleton ${className}`} />;
}

export function SkeletonRows({ rows = 4, className = '' }) {
  return (
    <div className={`space-y-3 ${className}`}>
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title = 'Nothing here yet', description, icon: Icon = Inbox, action }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-slate-50 text-slate-400">
        <Icon size={22} />
      </span>
      <div>
        <p className="text-[14px] font-bold text-ink">{title}</p>
        {description ? <p className="mx-auto mt-1 max-w-sm text-[12px] font-medium text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({ message, onRetry, compact = false }) {
  return (
    <div
      className={`flex ${compact ? 'items-center gap-3' : 'flex-col items-center gap-3 py-10 text-center'} rounded-widget bg-pink-50/60 px-5 py-4`}
    >
      <AlertCircle size={18} className="shrink-0 text-danger" />
      <div className={compact ? 'flex-1' : ''}>
        <p className="text-[12.5px] font-semibold text-ink">{message || 'Unable to load this data.'}</p>
        {!compact ? <p className="mt-1 text-[11.5px] font-medium text-muted">Check that the collector is running.</p> : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function Spinner({ label }) {
  return (
    <span className="inline-flex items-center gap-2 text-[12px] font-medium text-muted">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-300 border-t-primary" />
      {label}
    </span>
  );
}
