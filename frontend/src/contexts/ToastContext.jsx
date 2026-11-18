import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { CheckCircle2, AlertTriangle, Info, X } from 'lucide-react';

const ToastContext = createContext(null);

const TONES = {
  success: { icon: CheckCircle2, ring: 'border-emerald-100', iconClass: 'text-success', bar: 'bg-success' },
  error: { icon: AlertTriangle, ring: 'border-pink-100', iconClass: 'text-danger', bar: 'bg-danger' },
  info: { icon: Info, ring: 'border-blue-100', iconClass: 'text-primary', bar: 'bg-primary' },
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    (message, tone = 'success', title) => {
      const id = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
      setToasts((current) => [...current.slice(-3), { id, message, tone, title }]);
      window.setTimeout(() => dismiss(id), 4500);
      return id;
    },
    [dismiss]
  );

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex w-[340px] flex-col gap-3">
        {toasts.map((toast) => {
          const tone = TONES[toast.tone] || TONES.info;
          const Icon = tone.icon;
          return (
            <div
              key={toast.id}
              className={`pointer-events-auto animate-fade-up overflow-hidden rounded-widget border ${tone.ring} bg-surface shadow-lift`}
            >
              <div className="flex items-start gap-3 px-4 py-3.5">
                <Icon size={18} className={`mt-0.5 shrink-0 ${tone.iconClass}`} />
                <div className="min-w-0 flex-1">
                  {toast.title ? <p className="text-[13px] font-bold text-ink">{toast.title}</p> : null}
                  <p className="text-[12.5px] font-medium leading-relaxed text-muted">{toast.message}</p>
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  className="rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-50 hover:text-ink focus-ring"
                  aria-label="Dismiss notification"
                >
                  <X size={14} />
                </button>
              </div>
              <div className={`h-0.5 w-full ${tone.bar} opacity-60`} />
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used inside ToastProvider');
  return context;
}

export default ToastContext;
