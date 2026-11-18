import { TrendingDown, TrendingUp } from 'lucide-react';
import Card from './Card';

const TONES = {
  blue: 'bg-blue-50 text-primary',
  orange: 'bg-orange-50 text-accent',
  green: 'bg-emerald-50 text-success',
  pink: 'bg-pink-50 text-danger',
  purple: 'bg-purple-50 text-processing',
};

export default function StatCard({ label, value, hint, icon: Icon, tone = 'blue', trend, loading = false }) {
  return (
    <Card hover className="p-5">
      <div className="flex items-start justify-between">
        <span className={`grid h-10 w-10 place-items-center rounded-widget ${TONES[tone] || TONES.blue}`}>
          <Icon size={18} />
        </span>
        {trend ? (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[10.5px] font-bold ${
              trend.tone === 'negative'
                ? 'bg-pink-50 text-danger'
                : trend.tone === 'neutral'
                  ? 'bg-blue-50 text-primary'
                  : 'bg-emerald-50 text-success'
            }`}
          >
            {trend.direction === 'down' ? <TrendingDown size={11} /> : <TrendingUp size={11} />}
            {trend.value}
          </span>
        ) : null}
      </div>
      <p className="mt-4 text-[12px] font-semibold text-muted">{label}</p>
      {loading ? (
        <div className="skeleton mt-2 h-8 w-24" />
      ) : (
        <p className="mt-1 text-[30px] font-extrabold leading-none tracking-tight text-ink">{value}</p>
      )}
      {hint ? <p className="mt-2 text-[11.5px] font-medium text-muted">{hint}</p> : null}
    </Card>
  );
}
