/**
 * StatusFooter — Persistent bottom bar showing pipeline speed, ticks,
 * and quick controls for demo speed adjustment.
 * All emojis replaced with Lucide SVGs.
 */
'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Activity } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const SPEEDS = [
  { id: 'slow',   label: '2 tps',  hz: 2 },
  { id: 'normal', label: '4 tps',  hz: 4 },
  { id: 'fast',   label: '10 tps', hz: 10 },
  { id: 'turbo',  label: '25 tps', hz: 25 },
];

export default function StatusFooter({ tickId = 0, crisisMode = false, isConnected = false }) {
  const [activeSpeed, setActiveSpeed] = useState('normal');
  const [liveHz, setLiveHz] = useState(null);

  // Pull live tick rate from /api/metrics so the footer reflects reality,
  // not a hardcoded "4 Hz" placeholder.
  useEffect(() => {
    let cancelled = false;
    const fetchMetrics = async () => {
      try {
        const res = await fetch(`${API_URL}/api/metrics`);
        if (!cancelled && res.ok) {
          const m = await res.json();
          setLiveHz(m.ticks_per_second);
        }
      } catch {}
    };
    fetchMetrics();
    const id = setInterval(fetchMetrics, 3000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const displayHz = liveHz != null ? liveHz.toFixed(1) : (SPEEDS.find(s => s.id === activeSpeed)?.hz ?? 4);

  return (
    <footer className="status-footer">
      <div className="footer-section">
        <span className="footer-label">PIPELINE</span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '11px',
          color: 'var(--text-secondary)', marginLeft: '8px',
        }}>
          <Activity size={11} style={{ marginRight: 4, opacity: 0.5 }} />
          {displayHz} Hz · {tickId.toLocaleString()} ticks
        </span>
      </div>

      <div className="footer-section footer-center">
        {crisisMode && (
          <motion.span
            className="footer-crisis-badge"
            animate={{ opacity: [1, 0.5, 1] }}
            transition={{ repeat: Infinity, duration: 1 }}
          >
            <AlertTriangle size={12} />
            CRISIS ACTIVE
          </motion.span>
        )}
      </div>

      <div className="footer-section footer-right">
        <span className="footer-tick">
          Tick #{tickId.toLocaleString()}
        </span>
        <span className={`footer-status ${isConnected ? 'connected' : 'disconnected'}`}>
          <span className="footer-dot" />
          {isConnected ? 'STREAMING' : 'OFFLINE'}
        </span>
      </div>
    </footer>
  );
}
