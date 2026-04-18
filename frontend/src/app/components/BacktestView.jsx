/**
 * BacktestView — Displays backtest results from labeled crisis windows.
 * Shows ROC curves (rendered via Canvas 2D), AUC metrics, lead-time
 * histograms, and live backtest progress.
 */
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}min`;
}

function AUCBadge({ value }) {
  let color = '#22c55e';
  let label = 'Excellent';
  if (value < 0.7) { color = '#ef4444'; label = 'Poor'; }
  else if (value < 0.8) { color = '#f97316'; label = 'Fair'; }
  else if (value < 0.9) { color = '#eab308'; label = 'Good'; }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 10px', borderRadius: 'var(--radius-full)',
      background: `${color}20`, color, fontSize: 11, fontWeight: 700,
      fontFamily: 'var(--font-mono)',
    }}>
      AUC {value.toFixed(3)} · {label}
    </span>
  );
}

function MiniROC({ fpr, tpr, auc }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !fpr || !tpr) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    // Background
    ctx.fillStyle = 'rgba(18,20,30,0.4)';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {
      const p = (i / 4) * w;
      ctx.beginPath(); ctx.moveTo(p, 0); ctx.lineTo(p, h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, p); ctx.lineTo(w, p); ctx.stroke();
    }

    // Diagonal (random classifier)
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, h); ctx.lineTo(w, 0); ctx.stroke();
    ctx.setLineDash([]);

    // ROC curve
    const gradient = ctx.createLinearGradient(0, h, w, 0);
    gradient.addColorStop(0, '#ff8c00');
    gradient.addColorStop(1, '#c9a227');
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    for (let i = 0; i < fpr.length; i++) {
      const x = fpr[i] * w;
      const y = h - tpr[i] * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Fill under curve
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = '#ff8c00';
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;

    // AUC text
    ctx.fillStyle = '#94a3b8';
    ctx.font = '10px "JetBrains Mono", monospace';
    ctx.fillText(`AUC = ${auc.toFixed(3)}`, 6, 14);
  }, [fpr, tpr, auc]);

  return (
    <canvas
      ref={canvasRef}
      width={180}
      height={180}
      style={{ borderRadius: 'var(--radius-md)', border: '1px solid var(--border-primary)' }}
    />
  );
}

export default function BacktestView() {
  const [crises, setCrises] = useState([]);
  const [selected, setSelected] = useState([]);
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);

  // Load available crises list
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/backtest/crises`);
        if (res.ok && live) {
          const data = await res.json();
          setCrises(Array.isArray(data) ? data : []);
        }
      } catch { /* silent */ }
    })();
    return () => { live = false; };
  }, []);

  // Poll status while running
  useEffect(() => {
    if (!status?.running) return;
    const t = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/backtest/status`);
        if (res.ok) {
          const s = await res.json();
          setStatus(s);
          if (!s.running) {
            clearInterval(t);
            fetchResults();
          }
        }
      } catch { /* silent */ }
    }, 2000);
    return () => clearInterval(t);
  }, [status?.running]);

  const fetchResults = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/backtest/results`);
      if (res.ok) setResults(await res.json());
    } catch { /* silent */ }
  }, []);

  const runBacktest = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/backtest/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          crisis_names: selected.length > 0 ? selected : [],
          speed_multiplier: 5000,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setStatus(data.status || { running: true });
      }
    } catch (e) {
      console.error('Backtest start failed:', e);
    }
    setLoading(false);
  }, [selected]);

  const toggleCrisis = (name) => {
    setSelected(prev =>
      prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
    );
  };

  return (
    <div className="card backtest-card">
      <div className="card-header">
        <span className="card-title">Backtest Validation</span>
        <span className="card-badge">ROC / AUC</span>
      </div>

      {/* Crisis selector */}
      <div className="backtest-crisis-list">
        {crises.length === 0 && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', padding: 8 }}>
            Loading historical crisis windows…
          </div>
        )}
        {crises.map((c) => (
          <button
            key={c.name || c}
            className={`backtest-crisis-btn ${selected.includes(c.name || c) ? 'selected' : ''}`}
            onClick={() => toggleCrisis(c.name || c)}
          >
            <span className="backtest-crisis-name">{c.name || c}</span>
            {c.start && <span className="backtest-crisis-dates">{c.start} → {c.end}</span>}
          </button>
        ))}
      </div>

      {/* Run button */}
      <motion.button
        className="backtest-run-btn"
        onClick={runBacktest}
        disabled={loading || (status && status.running)}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
      >
        {status?.running ? (
          <>
            <span className="loading-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            Running {status.progress ? `(${(status.progress * 100).toFixed(0)}%)` : '...'}
          </>
        ) : loading ? (
          <>
            <span className="loading-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            Starting…
          </>
        ) : (
          'Run Backtest'
        )}
      </motion.button>

      {/* Results */}
      <AnimatePresence>
        {results && (
          <motion.div
            className="backtest-results"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            {results.per_crisis && Object.entries(results.per_crisis).map(([name, data]) => (
              <div key={name} className="backtest-crisis-result">
                <div className="backtest-crisis-result-header">
                  <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>{name}</span>
                  <AUCBadge value={data.auc || 0} />
                </div>

                <div className="backtest-metrics-row">
                  <div className="backtest-metric">
                    <div className="backtest-metric-label">Precision</div>
                    <div className="backtest-metric-value">{((data.precision || 0) * 100).toFixed(1)}%</div>
                  </div>
                  <div className="backtest-metric">
                    <div className="backtest-metric-label">Recall</div>
                    <div className="backtest-metric-value">{((data.recall || 0) * 100).toFixed(1)}%</div>
                  </div>
                  <div className="backtest-metric">
                    <div className="backtest-metric-label">Lead Time</div>
                    <div className="backtest-metric-value">{data.lead_time_ticks || '—'} ticks</div>
                  </div>
                  <div className="backtest-metric">
                    <div className="backtest-metric-label">FP Rate</div>
                    <div className="backtest-metric-value">{((data.false_positive_rate || 0) * 100).toFixed(1)}%</div>
                  </div>
                </div>

                {data.fpr && data.tpr && (
                  <div style={{ display: 'flex', justifyContent: 'center', marginTop: 8 }}>
                    <MiniROC fpr={data.fpr} tpr={data.tpr} auc={data.auc || 0} />
                  </div>
                )}
              </div>
            ))}

            {results.aggregate && (
              <div className="backtest-aggregate">
                <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Aggregate
                </span>
                <AUCBadge value={results.aggregate.mean_auc || 0} />
                <span style={{ fontSize: 11, color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                  {results.aggregate.total_crises || 0} crises · {formatDuration(results.aggregate.runtime_ms || 0)}
                </span>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
