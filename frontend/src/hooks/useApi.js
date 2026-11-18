import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Small data-fetching hook.
 *
 * `loader` is called on mount, whenever `deps` change, and every `interval`
 * milliseconds when polling is requested. Polls never flip the loading state,
 * so live pages do not flash skeletons on every tick.
 */
export function useApi(loader, deps = [], { interval = 0, enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    if (!enabled) {
      setState((prev) => ({ ...prev, loading: false }));
      return undefined;
    }
    let cancelled = false;
    let timer = null;

    const run = async (initial) => {
      if (initial) setState((prev) => ({ ...prev, loading: true }));
      try {
        const data = await loaderRef.current();
        if (!cancelled) setState({ data, error: null, loading: false });
      } catch (error) {
        if (!cancelled) setState((prev) => ({ ...prev, error: error.message || 'Request failed', loading: false }));
      }
    };

    run(true);
    if (interval > 0) timer = window.setInterval(() => run(false), interval);

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, interval, enabled, tick]);

  return { ...state, refresh, setData: (data) => setState((prev) => ({ ...prev, data })) };
}

export default useApi;
