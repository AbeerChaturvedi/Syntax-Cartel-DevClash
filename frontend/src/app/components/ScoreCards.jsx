/**
 * ScoreCards — Model output score cards (IF, LSTM, Combined, Correlation)
 */
'use client';

import { motion } from 'framer-motion';

function getScoreColor(score) {
  if (score < 0.3) return '#4ade80';
  if (score < 0.5) return '#facc15';
  if (score < 0.7) return '#fb923c';
  return '#f87171';
}

function ScoreCard({ label, value, maxValue = 1 }) {
  const color = getScoreColor(value);
  const pct = Math.min(100, (value / maxValue) * 100);

  return (
    <div className="score-card">
      <div className="score-card-label">{label}</div>
      <div className="score-card-value" style={{ color }}>
        {(value * 100).toFixed(1)}
        <span style={{ fontSize: '14px', opacity: 0.5 }}>%</span>
      </div>
      <div className="score-card-bar">
        <motion.div
          className="score-card-bar-fill"
          style={{ background: color }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.3, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}

const SEVERITY_STYLES = {
  NORMAL:   { bg: 'rgba(34,197,94,0.15)',  color: '#22c55e' },
  ELEVATED: { bg: 'rgba(234,179,8,0.15)',   color: '#eab308' },
  HIGH:     { bg: 'rgba(249,115,22,0.15)',  color: '#f97316' },
  SEVERE:   { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444' },
  CRITICAL: { bg: 'rgba(220,38,38,0.2)',    color: '#dc2626' },
};

export default function ScoreCards({ scores = {} }) {
  const ifScore = scores.isolation_forest || 0;
  const lstmScore = scores.lstm_autoencoder || 0;
  const combined = scores.combined_anomaly || 0;
  const severity = scores.severity || 'NORMAL';
  const style = SEVERITY_STYLES[severity] || SEVERITY_STYLES.NORMAL;

  return (
    <div className="card score-cards-container">
      <div className="card-header">
        <span className="card-title">Model Outputs</span>
        <span
          className="card-badge"
          style={{ background: style.bg, color: style.color }}
        >
          {severity}
        </span>
      </div>
      <div className="score-cards-grid">
        <ScoreCard label="Isolation Forest" value={ifScore} />
        <ScoreCard label="LSTM Autoencoder" value={lstmScore} />
        <ScoreCard label="Combined Anomaly" value={combined} />
        <ScoreCard label="CISS Stress" value={scores.ciss || 0} />
      </div>
    </div>
  );
}
