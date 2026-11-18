/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#f8f9fc',
        surface: '#ffffff',
        ink: '#1e293b',
        muted: '#64748b',
        line: '#f3f4f6',
        primary: '#0d6efd',
        accent: '#f97316',
        success: '#10b981',
        danger: '#ec4899',
        warning: '#f97316',
        info: '#0d6efd',
        processing: '#a855f7',
        tooltip: '#111827',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        card: '24px',
        widget: '16px',
        btn: '12px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16, 24, 40, 0.04)',
        lift: '0 12px 30px -12px rgba(15, 23, 42, 0.18)',
        cta: '0 10px 24px -10px rgba(13, 110, 253, 0.65)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'flow': {
          '0%': { strokeDashoffset: '24' },
          '100%': { strokeDashoffset: '0' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.35' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.35s ease-out both',
        flow: 'flow 1s linear infinite',
        'pulse-soft': 'pulse-soft 1.8s ease-in-out infinite',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
};
