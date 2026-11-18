export const inputClass =
  'focus-ring h-10 w-full rounded-btn border border-line bg-white px-3.5 text-[12.5px] font-medium text-ink placeholder:text-slate-400 transition-colors hover:border-slate-200';

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`block ${className}`}>
      {label ? <span className="mb-1.5 block text-[11.5px] font-semibold text-muted">{label}</span> : null}
      {children}
      {hint ? <span className="mt-1 block text-[10.5px] font-medium text-slate-400">{hint}</span> : null}
    </label>
  );
}

export function Input({ className = '', ...rest }) {
  return <input className={`${inputClass} ${className}`} {...rest} />;
}

export function Select({ className = '', children, ...rest }) {
  return (
    <select className={`${inputClass} cursor-pointer pr-8 ${className}`} {...rest}>
      {children}
    </select>
  );
}

export function TextArea({ className = '', ...rest }) {
  return (
    <textarea
      className={`focus-ring w-full rounded-btn border border-line bg-white px-3.5 py-2.5 text-[12.5px] font-medium text-ink placeholder:text-slate-400 ${className}`}
      {...rest}
    />
  );
}

export function Toggle({ checked, onChange, label, description, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="focus-ring flex items-center gap-3 rounded-btn text-left disabled:opacity-50"
    >
      <span
        className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors duration-300 ${
          checked ? 'bg-primary' : 'bg-slate-200'
        }`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-300 ${
            checked ? 'translate-x-[18px]' : 'translate-x-[3px]'
          }`}
        />
      </span>
      {label ? (
        <span>
          <span className="block text-[12px] font-semibold text-ink">{label}</span>
          {description ? <span className="block text-[10.5px] font-medium text-muted">{description}</span> : null}
        </span>
      ) : null}
    </button>
  );
}
