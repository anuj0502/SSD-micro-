const VARIANTS = {
  primary: 'bg-primary text-white shadow-cta hover:bg-blue-600',
  secondary: 'border border-line bg-white text-ink hover:border-slate-200 hover:bg-slate-50',
  subtle: 'bg-slate-50 text-ink hover:bg-slate-100',
  ghost: 'text-muted hover:bg-slate-50 hover:text-ink',
  danger: 'bg-danger text-white hover:bg-pink-600',
  accent: 'bg-accent text-white hover:bg-orange-600',
};

const SIZES = {
  sm: 'h-8 gap-1.5 px-3 text-[12px]',
  md: 'h-10 gap-2 px-4 text-[13px]',
  lg: 'h-11 gap-2 px-5 text-[13.5px]',
};

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  icon: Icon,
  loading = false,
  className = '',
  type = 'button',
  ...rest
}) {
  return (
    <button
      type={type}
      className={`focus-ring inline-flex items-center justify-center rounded-btn font-semibold transition-all duration-300 disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      disabled={loading || rest.disabled}
      {...rest}
    >
      {loading ? (
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
      ) : Icon ? (
        <Icon size={size === 'sm' ? 14 : 16} />
      ) : null}
      {children}
    </button>
  );
}

export function IconButton({ icon: Icon, label, className = '', size = 16, ...rest }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`focus-ring inline-grid h-9 w-9 place-items-center rounded-btn border border-line bg-white text-muted transition-all duration-300 hover:border-slate-200 hover:text-ink ${className}`}
      {...rest}
    >
      <Icon size={size} />
    </button>
  );
}
