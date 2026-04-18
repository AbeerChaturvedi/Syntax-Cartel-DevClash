/**
 * useWebSocket — Custom hook for WebSocket connection with useRef buffering.
 * 
 * CRITICAL PATTERN: Data flows into useRef (no re-render), then a 
 * requestAnimationFrame loop flushes the buffer into useState at 60fps max.
 * This prevents React reconciler thrashing from high-frequency market data.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws/dashboard';
const RECONNECT_DELAY_MS = 2000;
const HEARTBEAT_INTERVAL_MS = 15000;

export function useWebSocket() {
  const [isConnected, setIsConnected] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);
  const [connectionAttempts, setConnectionAttempts] = useState(0);

  const wsRef = useRef(null);
  const bufferRef = useRef(null);
  const rafRef = useRef(null);
  const heartbeatRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const mountedRef = useRef(true);

  // Flush buffer to state at display refresh rate
  const flushBuffer = useCallback(() => {
    if (bufferRef.current && mountedRef.current) {
      setDashboardData(bufferRef.current);
      bufferRef.current = null;
    }
    rafRef.current = requestAnimationFrame(flushBuffer);
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
          // Write to mutable ref — NO re-render triggered
          bufferRef.current = data;
        } catch (e) {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        clearInterval(heartbeatRef.current);
        console.log('[Velure WS] Disconnected. Reconnecting...');

        setConnectionAttempts(prev => prev + 1);
        reconnectTimeoutRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      ws.onerror = (err) => {
        console.error('[Velure WS] Error:', err);
        ws.close();
      };
    } catch (e) {
      console.error('[Velure WS] Connection failed:', e);
      reconnectTimeoutRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    // Start RAF flush loop
    rafRef.current = requestAnimationFrame(flushBuffer);

    // Connect WebSocket
    connect();

    return () => {
      mountedRef.current = false;
      cancelAnimationFrame(rafRef.current);
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
