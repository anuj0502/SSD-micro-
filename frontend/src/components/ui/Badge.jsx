import { statusStyle } from '../../utils/format';

export default function Badge({ status, label, dot = true, className = '' }) {
  const tone = statusStyle(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${tone.soft} ${className}`}
    >
      {dot ? <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} /> : null}
      {label || tone.label}
    </span>
  );
}

export function StatusDot({ status, className = '' }) {
  const tone = statusStyle(status);
  return <span className={`inline-block h-2 w-2 rounded-full ${tone.dot} ${className}`} />;
}
