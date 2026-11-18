export default function Card({ children, className = '', hover = false, ...rest }) {
  return (
    <div
      className={`rounded-card border border-line bg-surface shadow-card ${hover ? 'card-hover' : ''} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, action, icon: Icon, className = '' }) {
  return (
    <div className={`flex items-start justify-between gap-4 ${className}`}>
      <div className="flex items-start gap-3">
        {Icon ? (
          <span className="mt-0.5 grid h-9 w-9 place-items-center rounded-xl bg-slate-50 text-muted">
            <Icon size={17} />
          </span>
        ) : null}
        <div>
          <h3 className="text-[16px] font-bold leading-tight text-ink">{title}</h3>
          {subtitle ? <p className="mt-1 text-[12px] font-medium text-muted">{subtitle}</p> : null}
        </div>
      </div>
      {action}
    </div>
  );
}
