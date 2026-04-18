/**
 * useWebSocket — buffered WS hook tuned for institutional readability.
 *
 * Inbound ticks land in a useRef (no re-render). A setInterval flushes the
 * latest buffer into React state at DISPLAY_FLUSH_MS (slow enough that a
 * trader can read a number before it changes again).
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/dashboard';
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
const HEARTBEAT_INTERVAL_MS = 15000;
// Slow display cadence — a trader cannot act on numbers that change at 60fps.
// Backend ML inference still runs on its own faster cadence; this only
// throttles what the human sees.
const DISPLAY_FLUSH_MS = 2000;

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);
  const [connectionAttempts, setConnectionAttempts] = useState(0);

  const wsRef = useRef(null);
  const bufferRef = useRef(null);
  const flushTimerRef = useRef(null);
  const heartbeatRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const mountedRef = useRef(true);

  // Flush latest buffered tick into state at display cadence (2s).
  // Critical alerts bypass this throttle (see ws.onmessage below).
  const flushBuffer = useCallback(() => {
    if (bufferRef.current && mountedRef.current) {
      setDashboardData(bufferRef.current);
      bufferRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        setConnectionAttempts(0);
        console.log('[Velure WS] Connected');

        // Start heartbeat
        heartbeatRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
          }
        }, HEARTBEAT_INTERVAL_MS);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'pong') return;
          bufferRef.current = data;
          // Critical alerts bypass the display throttle so the banner
          // appears immediately instead of waiting up to 2s.
          const sev = data?.scores?.severity;
          if (sev === 'CRITICAL' || data?.alert?.severity === 'CRITICAL') {
            if (mountedRef.current) setDashboardData(data);
            bufferRef.current = null;
          }
        } catch (e) {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        clearInterval(heartbeatRef.current);
        console.log('[Velure WS] Disconnected. Reconnecting...');

        setConnectionAttempts(prev => {
          const attempt = prev + 1;
          // Exponential backoff with jitter: 1s, 2s, 4s, ... capped at 15s
          const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, attempt - 1), RECONNECT_MAX_MS);
          const jitter = delay * 0.2 * Math.random();
          reconnectTimeoutRef.current = setTimeout(connect, delay + jitter);
          return attempt;
        });
      };

      ws.onerror = (err) => {
        console.error('[Velure WS] Error:', err);
        ws.close();
      };
    } catch (e) {
      console.error('[Velure WS] Connection failed:', e);
      const delay = Math.min(RECONNECT_BASE_MS * 2, RECONNECT_MAX_MS);
      reconnectTimeoutRef.current = setTimeout(connect, delay);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    // Slow display flush — institutional readability over flicker.
    flushTimerRef.current = setInterval(flushBuffer, DISPLAY_FLUSH_MS);

    // Connect WebSocket
    connect();

    return () => {
      mountedRef.current = false;
      clearInterval(flushTimerRef.current);
      clearInterval(heartbeatRef.current);
      clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect, flushBuffer]);

  return {
    isConnected,
    dashboardData,
    connectionAttempts,
  };
}
