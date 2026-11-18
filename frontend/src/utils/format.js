export const NUMBER = new Intl.NumberFormat('en-US');

export function formatNumber(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (Math.abs(number) >= 10_000) return `${(number / 1000).toFixed(1)}k`;
  return NUMBER.format(Number(number.toFixed(digits)));
}

export function formatDecimal(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(digits);
}

export function formatMs(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const number = Number(value);
  if (number >= 60_000) return `${(number / 60_000).toFixed(1)}m`;
  if (number >= 1000) return `${(number / 1000).toFixed(2)}s`;
  if (number >= 100) return `${Math.round(number)}ms`;
  return `${number.toFixed(number < 10 ? 1 : 0)}ms`;
}

export function formatPercent(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  return `${Number(value).toFixed(digits)}%`;
}

export function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const bytes = Number(value);
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(units.length - 1, Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024)));
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatTime(ts, withSeconds = true) {
  if (!ts) return '—';
  const date = new Date(Number(ts) * 1000);
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hour12: false,
  });
}

export function formatDateTime(ts) {
  if (!ts) return '—';
  return new Date(Number(ts) * 1000).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function timeAgo(ts) {
  if (!ts) return '—';
  const seconds = Math.max(0, Date.now() / 1000 - Number(ts));
  if (seconds < 5) return 'just now';
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export function shortId(value, head = 10, tail = 4) {
  if (!value) return '—';
  const text = String(value);
  if (text.length <= head + tail + 1) return text;
  return `${text.slice(0, head)}…${text.slice(-tail)}`;
}

export function toUnixSeconds(date) {
  return date.getTime() / 1000;
}

export const STATUS_STYLES = {
  success: { label: 'Success', dot: 'bg-success', text: 'text-emerald-600', soft: 'bg-emerald-50 text-emerald-600' },
  error: { label: 'Error', dot: 'bg-danger', text: 'text-pink-600', soft: 'bg-pink-50 text-pink-600' },
  slow: { label: 'Slow', dot: 'bg-accent', text: 'text-orange-600', soft: 'bg-orange-50 text-orange-600' },
  pending: { label: 'Pending', dot: 'bg-processing', text: 'text-purple-600', soft: 'bg-purple-50 text-purple-600' },
  healthy: { label: 'Healthy', dot: 'bg-success', text: 'text-emerald-600', soft: 'bg-emerald-50 text-emerald-600' },
  warning: { label: 'Warning', dot: 'bg-accent', text: 'text-orange-600', soft: 'bg-orange-50 text-orange-600' },
  degraded: { label: 'Degraded', dot: 'bg-accent', text: 'text-orange-600', soft: 'bg-orange-50 text-orange-600' },
  uploaded: { label: 'Uploaded', dot: 'bg-success', text: 'text-emerald-600', soft: 'bg-emerald-50 text-emerald-600' },
  failed: { label: 'Failed', dot: 'bg-danger', text: 'text-pink-600', soft: 'bg-pink-50 text-pink-600' },
  running: { label: 'Running', dot: 'bg-primary', text: 'text-blue-600', soft: 'bg-blue-50 text-blue-600' },
  completed: { label: 'Completed', dot: 'bg-success', text: 'text-emerald-600', soft: 'bg-emerald-50 text-emerald-600' },
  stopped: { label: 'Stopped', dot: 'bg-slate-300', text: 'text-slate-500', soft: 'bg-slate-100 text-slate-500' },
  unavailable: { label: 'Unavailable', dot: 'bg-danger', text: 'text-pink-600', soft: 'bg-pink-50 text-pink-600' },
  down: { label: 'Down', dot: 'bg-danger', text: 'text-pink-600', soft: 'bg-pink-50 text-pink-600' },
  ok: { label: 'Operational', dot: 'bg-success', text: 'text-emerald-600', soft: 'bg-emerald-50 text-emerald-600' },
};

export function statusStyle(status) {
  return (
    STATUS_STYLES[String(status || '').toLowerCase()] || {
      label: status || 'Unknown',
      dot: 'bg-slate-300',
      text: 'text-slate-500',
      soft: 'bg-slate-100 text-slate-500',
    }
  );
}

export function decisionLabel(reason) {
  return {
    error: 'Error retained',
    slow: 'Slow retained',
    success_sampled: 'Sampled',
    success_discarded: 'Discarded',
  }[reason] || reason || '—';
}
