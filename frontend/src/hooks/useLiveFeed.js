import { useEffect, useRef, useState } from 'react';

/**
 * Subscribes to the collector's WebSocket snapshot feed.
 * Reconnects with a bounded linear backoff; the socket is closed on unmount.
 */
export function useLiveFeed(range, enabled) {
  const [snapshot, setSnapshot] = useState(null);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef(null);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return undefined;
    }
    let disposed = false;
    let retry = 0;
    let timer = null;

    const connect = () => {
      if (disposed) return;
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${protocol}://${window.location.host}/api/ws/live?range=${encodeURIComponent(range)}`;
      let socket;
      try {
        socket = new WebSocket(url);
      } catch {
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        retry = 0;
        setConnected(true);
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type === 'snapshot') setSnapshot(message);
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (disposed) return;
        retry = Math.min(retry + 1, 5);
        timer = window.setTimeout(connect, retry * 1000);
      };
      socket.onerror = () => {
        try {
          socket.close();
        } catch {
          /* noop */
        }
      };
    };

    connect();
    return () => {
      disposed = true;
      if (timer) window.clearTimeout(timer);
      try {
        socketRef.current?.close();
      } catch {
        /* noop */
      }
    };
  }, [range, enabled]);

  return { snapshot, connected };
}

export default useLiveFeed;
