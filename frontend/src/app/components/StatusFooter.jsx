/**
 * StatusFooter — Persistent bottom bar showing pipeline speed, ticks,
 * and quick controls for demo speed adjustment.
 * All emojis replaced with Lucide SVGs.
 */
'use client';

import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const SPEEDS = [
  { id: 'slow',   label: '2 tps',  hz: 2 },
  { id: 'normal', label: '4 tps',  hz: 4 },
  { id: 'fast',   label: '10 tps', hz: 10 },
  { id: 'turbo',  label: '25 tps', hz: 25 },
];

export default function StatusFooter({ tickId = 0, crisisMode = false, isConnected = false }) {
  const [activeSpeed, setActiveSpeed] = useState('normal');

  const setSpeed = useCallback(async (mode) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(`${API_URL}/api/speed/${mode}`, { method: 'POST', signal: controller.signal });
      if (res.ok) setActiveSpeed(mode);
    } catch {
      // silent
    } finally {
      clearTimeout(timeout);
    }
  }, []);

  return (
    <footer className="status-footer">
      <div className="footer-section">
        <span className="footer-label">PIPELINE</span>
        <div className="speed-controls">
          {SPEEDS.map(s => (
            <button
              key={s.id}
              className={`speed-btn ${activeSpeed === s.id ? 'active' : ''}`}
              onClick={() => setSpeed(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
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
