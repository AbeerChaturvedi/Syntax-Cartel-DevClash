/**
 * ReplayController — Controls historical data replay through the live pipeline.
 * Streams actual crisis-era market data at configurable speeds.
 * All emojis replaced with Lucide SVGs.
 */
'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Building, Bug, Home, Square, Play } from 'lucide-react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const REPLAY_PRESETS = [
  {
    id: 'lehman',
    name: 'Lehman 2008',
    icon: Building,
    start: '2008-09-10',
    end: '2008-09-20',
    description: 'Sep 10-20, 2008 -- Credit meltdown',
    color: '#ef4444',
  },
  {
    id: 'covid',
    name: 'COVID 2020',
    icon: Bug,
    start: '2020-03-05',
    end: '2020-03-15',
    description: 'Mar 5-15, 2020 -- Pandemic panic',
    color: '#f97316',
  },
  {
    id: 'svb',
    name: 'SVB 2023',
    icon: Home,
    start: '2023-03-08',
    end: '2023-03-14',
    description: 'Mar 8-14, 2023 -- Bank run contagion',
    color: '#eab308',
  },
];

const SPEED_OPTIONS = [
  { label: '1x', value: 1 },
  { label: '10x', value: 10 },
  { label: '60x', value: 60 },
  { label: '100x', value: 100 },
  { label: '500x', value: 500 },
];

export default function ReplayController() {
  const [status, setStatus] = useState({ running: false });
  const [selectedPreset, setSelectedPreset] = useState(null);
  const [speed, setSpeed] = useState(60);
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [loading, setLoading] = useState(false);
  const [showCustom, setShowCustom] = useState(false);

  // Poll replay status
  useEffect(() => {
    if (!status.running) return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/replay/status`);
        if (res.ok) {
          const s = await res.json();
          setStatus(s);
        }
      } catch { /* silent */ }
    }, 1000);
    return () => clearInterval(t);
  }, [status.running]);

  const startReplay = useCallback(async (startDate, endDate) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/replay/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          speed_multiplier: speed,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.ok) {
          setStatus({ running: true, ...data.status });
        }
      }
    } catch (e) {
      console.error('Replay start failed:', e);
    }
    setLoading(false);
  }, [speed]);

  const stopReplay = useCallback(async () => {
    setLoading(true);
    try {
      await fetch(`${API_URL}/api/replay/stop`, { method: 'POST' });
      setStatus({ running: false });
    } catch { /* silent */ }
    setLoading(false);
    setSelectedPreset(null);
  }, []);

  const progress = status.progress || 0;
  const framesProcessed = status.frames_processed || 0;
  const totalFrames = status.total_frames || 0;

  return (
    <div className="card replay-card">
      <div className="card-header">
        <span className="card-title">Historical Replay</span>
        <span
          className="card-badge"
          style={{
            color: status.running ? 'var(--red)' : 'var(--text-tertiary)',
            borderColor: status.running ? 'var(--red)' : 'var(--border-active)',
          }}
        >
          {status.running ? 'REPLAYING' : 'READY'}
        </span>
      </div>

      {status.running ? (
        /* Active replay view */
        <div className="replay-active">
          <div className="replay-progress-wrap">
            <div className="replay-progress-bar">
              <motion.div
                className="replay-progress-fill"
                animate={{ width: `${progress * 100}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <div className="replay-progress-text">
              {(progress * 100).toFixed(1)}% -- {framesProcessed.toLocaleString()} / {totalFrames.toLocaleString()} frames
            </div>
          </div>

          {selectedPreset && (
            <div className="replay-active-label">
              {(() => {
                const Icon = selectedPreset.icon;
                return <Icon size={18} />;
              })()}
              <span>{selectedPreset.name}</span>
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>@ {speed}x</span>
            </div>
          )}

          <motion.button
            className="replay-stop-btn"
            onClick={stopReplay}
            disabled={loading}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
          >
            <Square size={14} /> Stop Replay
          </motion.button>
        </div>
      ) : (
        <>
          {/* Speed selector */}
          <div className="replay-speed-row">
            <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontWeight: 600 }}>Speed:</span>
            <div className="replay-speed-btns">
              {SPEED_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  className={`replay-speed-btn ${speed === opt.value ? 'active' : ''}`}
                  onClick={() => setSpeed(opt.value)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Preset buttons */}
          <div className="replay-presets">
            {REPLAY_PRESETS.map((preset) => {
              const Icon = preset.icon;
              return (
                <motion.button
                  key={preset.id}
                  className="replay-preset-btn"
                  onClick={() => {
                    setSelectedPreset(preset);
                    startReplay(preset.start, preset.end);
                  }}
                  disabled={loading}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  style={{ '--preset-color': preset.color }}
                >
                  <Icon className="replay-preset-icon" size={20} />
                  <div className="replay-preset-info">
                    <span className="replay-preset-name">{preset.name}</span>
                    <span className="replay-preset-desc">{preset.description}</span>
                  </div>
                </motion.button>
              );
            })}
          </div>

          {/* Custom date range */}
          <button className="replay-custom-toggle" onClick={() => setShowCustom(!showCustom)}>
            {showCustom ? 'Hide Custom Range' : 'Custom Date Range'}
          </button>
          <AnimatePresence>
            {showCustom && (
              <motion.div
                className="replay-custom"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
              >
                <div className="replay-custom-inputs">
                  <div className="replay-custom-field">
                    <label>Start</label>
                    <input
                      type="date"
                      className="portfolio-input"
                      value={customStart}
                      onChange={(e) => setCustomStart(e.target.value)}
                    />
                  </div>
                  <div className="replay-custom-field">
                    <label>End</label>
                    <input
                      type="date"
                      className="portfolio-input"
                      value={customEnd}
                      onChange={(e) => setCustomEnd(e.target.value)}
                    />
                  </div>
                </div>
                <motion.button
                  className="replay-custom-start-btn"
                  onClick={() => startReplay(customStart, customEnd)}
                  disabled={loading || !customStart || !customEnd}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                >
                  <Play size={12} /> Start Custom Replay
                </motion.button>
              </motion.div>
            )}
          </AnimatePresence>
        </>
      )}
    </div>
  );
}
