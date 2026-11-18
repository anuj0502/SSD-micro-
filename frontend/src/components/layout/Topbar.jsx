import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Bell, Menu, RefreshCw, Search, PanelRight, Wifi, WifiOff } from 'lucide-react';

import { TIME_RANGES, useApp } from '../../contexts/AppContext';
import api from '../../services/api';
import { timeAgo } from '../../utils/format';
import { Toggle } from '../ui/Fields';

export default function Topbar({ onOpenNav, onOpenActivity }) {
  const navigate = useNavigate();
  const { range, setRange, live, setLive, search, setSearch, refresh, refreshTick } = useApp();
  const [draft, setDraft] = useState(search);
  const [refreshing, setRefreshing] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [notificationsError, setNotificationsError] = useState(null);
  const bellRef = useRef(null);
  const refreshTimer = useRef(null);

  useEffect(() => setDraft(search), [search]);

  useEffect(() => {
    if (!bellOpen) return undefined;
    let cancelled = false;
    api
      .events({ limit: 6, hours: 24 })
      .then((data) => {
        if (!cancelled) {
          setNotifications(data.items || []);
          setNotificationsError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) setNotificationsError(error.message);
      });
    const onClick = (event) => {
      if (bellRef.current && !bellRef.current.contains(event.target)) setBellOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => {
      cancelled = true;
      document.removeEventListener('mousedown', onClick);
    };
  }, [bellOpen]);

  const submitSearch = (event) => {
    event.preventDefault();
    const query = draft.trim();
    if (!query) return;
    setSearch(query);
    navigate(`/traces?q=${encodeURIComponent(query)}`);
  };

  const onRefresh = () => {
    setRefreshing(true);
    refresh();
    window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => setRefreshing(false), 700);
  };

  return (
    <header className="z-20 flex h-[76px] shrink-0 items-center gap-3 border-b border-line bg-canvas px-4 sm:px-6">
      <button
        type="button"
        onClick={onOpenNav}
        className="focus-ring grid h-9 w-9 shrink-0 place-items-center rounded-btn border border-line bg-white text-muted lg:hidden"
        aria-label="Open navigation"
      >
        <Menu size={17} />
      </button>

      <form onSubmit={submitSearch} className="relative min-w-0 flex-1 max-w-[420px]">
        <Search size={15} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Search trace ID or operation…"
          className="h-10 w-full rounded-full border border-line bg-white pl-10 pr-4 text-[12px] font-medium text-ink shadow-card outline-none transition-all duration-300 placeholder:text-slate-400 focus:border-blue-200 focus:ring-2 focus:ring-primary/10"
          aria-label="Global search"
        />
      </form>

      <div className="ml-auto flex items-center gap-2">
        <select
          value={range}
          onChange={(event) => setRange(event.target.value)}
          className="hidden h-9 cursor-pointer rounded-btn border border-line bg-white px-3 text-[11.5px] font-semibold text-ink outline-none transition-colors hover:border-slate-200 focus:ring-2 focus:ring-primary/10 sm:block"
          aria-label="Time range"
        >
          {TIME_RANGES.map((option) => (
            <option key={option.key} value={option.key}>
              {option.label}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={onRefresh}
          className="focus-ring grid h-9 w-9 place-items-center rounded-btn border border-line bg-white text-muted transition-colors hover:text-ink"
          aria-label="Refresh data"
          title="Refresh data"
        >
          <RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} />
        </button>

        <div className="hidden h-9 items-center gap-2 rounded-btn border border-line bg-white px-3 md:flex">
          <span className={`flex items-center gap-1.5 text-[11px] font-bold ${live ? 'text-success' : 'text-muted'}`}>
            {live ? <Wifi size={13} /> : <WifiOff size={13} />}
            Live
          </span>
          <Toggle checked={live} onChange={setLive} />
        </div>

        <div className="relative" ref={bellRef}>
          <button
            type="button"
            onClick={() => setBellOpen((value) => !value)}
            className="focus-ring relative grid h-9 w-9 place-items-center rounded-btn border border-line bg-white text-muted transition-colors hover:text-ink"
            aria-label="Notifications"
          >
            <Bell size={16} />
            <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-danger" />
          </button>
          {bellOpen ? (
            <div className="absolute right-0 top-11 z-40 w-[320px] animate-fade-up overflow-hidden rounded-widget border border-line bg-white shadow-lift">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <p className="text-[12.5px] font-bold text-ink">System events</p>
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted">24h</span>
              </div>
              <div className="panel-scroll max-h-72 overflow-y-auto">
                {notificationsError ? (
                  <p className="px-4 py-6 text-center text-[11.5px] font-medium text-muted">{notificationsError}</p>
                ) : notifications.length === 0 ? (
                  <p className="px-4 py-6 text-center text-[11.5px] font-medium text-muted">No events recorded yet.</p>
                ) : (
                  <ul className="divide-y divide-line">
                    {notifications.map((event) => (
                      <li key={event.id} className="flex gap-2.5 px-4 py-3">
                        <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                        <div className="min-w-0">
                          <p className="truncate text-[11.5px] font-semibold text-ink">{event.message}</p>
                          <p className="mt-0.5 text-[10.5px] font-medium text-muted">
                            {event.category} · {timeAgo(event.ts)}
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <button
                type="button"
                onClick={() => {
                  setBellOpen(false);
                  navigate('/live');
                }}
                className="flex w-full items-center justify-center gap-2 border-t border-line px-4 py-3 text-[11.5px] font-bold text-primary transition-colors hover:bg-blue-50/50"
              >
                <Activity size={13} /> Open live view
              </button>
            </div>
          ) : null}
        </div>

        <button
          type="button"
          onClick={onOpenActivity}
          className="focus-ring grid h-9 w-9 place-items-center rounded-btn border border-line bg-white text-muted transition-colors hover:text-ink xl:hidden"
          aria-label="Open activity panel"
        >
          <PanelRight size={16} />
        </button>
      </div>
    </header>
  );
}
