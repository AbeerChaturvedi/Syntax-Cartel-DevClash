/**
 * SpeedControl — Pipeline tick-rate control for demo presentations.
 * Adjusts simulation speed from 2Hz (slow) to 25Hz (turbo).
 */
'use client';

import { useState, useCallback } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const SPEEDS = [
  { mode: 'slow', label: '2 Hz', hz: 2, color: '#22c55e' },
  { mode: 'normal', label: '4 Hz', hz: 4, color: '#6366f1' },
  { mode: 'fast', label: '10 Hz', hz: 10, color: '#f97316' },
  { mode: 'turbo', label: '25 Hz', hz: 25, color: '#ef4444' },
];

export default function SpeedControl() {
  const [active, setActive] = useState('normal');
  const [loading, setLoading] = useState(false);

  const setSpeed = useCallback(async (mode) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/speed/${mode}`, { method: 'POST' });
      if (res.ok) setActive(mode);
    } catch (e) {
      console.error('Speed change failed:', e);
    }
    setLoading(false);
  }, []);

  return (
    <div className="speed-control">
      {SPEEDS.map((s) => (
        <button
          key={s.mode}
          className={`speed-btn ${active === s.mode ? 'active' : ''}`}
          onClick={() => setSpeed(s.mode)}
          disabled={loading}
          style={{
            '--speed-color': s.color,
          }}
          title={`${s.label} tick rate`}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}
