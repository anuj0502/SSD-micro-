import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import api from '../services/api';
import useApi from '../hooks/useApi';

const AppContext = createContext(null);

export const TIME_RANGES = [
  { key: '15m', label: 'Last 15 min' },
  { key: '1h', label: 'Last 1 hour' },
  { key: '6h', label: 'Last 6 hours' },
  { key: '24h', label: 'Last 24 hours' },
  { key: '7d', label: 'Last 7 days' },
];

export function AppProvider({ children }) {
  const [range, setRange] = useState('1h');
  const [live, setLive] = useState(true);
  const [search, setSearch] = useState('');
  const [refreshTick, setRefreshTick] = useState(0);

  const refresh = useCallback(() => setRefreshTick((value) => value + 1), []);

  const healthQuery = useApi(() => api.health(), [], { interval: 10000 });
  const servicesQuery = useApi(() => api.services(range), [range, refreshTick], { interval: 20000 });

  const value = useMemo(
    () => ({
      range,
      setRange,
      live,
      setLive,
      search,
      setSearch,
      refreshTick,
      refresh,
      health: healthQuery.data,
      healthError: healthQuery.error,
      healthLoading: healthQuery.loading,
      refreshHealth: healthQuery.refresh,
      services: servicesQuery.data,
    }),
    [
      range,
      live,
      search,
      refreshTick,
      refresh,
      healthQuery.data,
      healthQuery.error,
      healthQuery.loading,
      healthQuery.refresh,
      servicesQuery.data,
    ]
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useApp must be used inside AppProvider');
  return context;
}

export default AppContext;
