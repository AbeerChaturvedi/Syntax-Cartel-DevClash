/**
 * ScoreCards — Model output score cards (IF, LSTM, Combined, Correlation)
 */
'use client';

import { motion } from 'framer-motion';
import { useAnimatedNumber } from '@/lib/useAnimatedNumber';

function getScoreColor(score) {
  if (score < 0.3) return '#10b981';
  if (score < 0.5) return '#f59e0b';
  if (score < 0.7) return '#fb7185';
  return '#f43f5e';
}

function ScoreCard({ label, value, maxValue = 1 }) {
  const color = getScoreColor(value);
  const anim = useAnimatedNumber(value);
  const pct = Math.min(100, (anim / maxValue) * 100);
  const hot = value >= 0.5;

  return (
    <div
      className="score-card"
      style={{
        borderRadius: 12,
        transition: 'box-shadow 400ms ease',
        boxShadow: hot ? `0 0 26px ${color}30, inset 0 0 0 1px ${color}50` : undefined,
      }}
    >
      <div className="score-card-label">{label}</div>
      <div className="score-card-value" style={{ color, textShadow: hot ? `0 0 18px ${color}80` : undefined, fontVariantNumeric: 'tabular-nums' }}>
        {(anim * 100).toFixed(1)}
        <span style={{ fontSize: '14px', opacity: 0.5 }}>%</span>
      </div>
      <div className="score-card-bar">
        <motion.div
          className="score-card-bar-fill"
          style={{ background: color, boxShadow: `0 0 10px ${color}70` }}
          animate={{ width: `${pct}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 22 }}
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
