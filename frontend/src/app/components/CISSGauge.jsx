/**
 * CISSGauge — Composite Indicator of Systemic Stress
 * Animated arc gauge with dynamic color transitions.
 */
'use client';

import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

function getColor(score) {
  if (score < 0.3) return { color: '#22c55e', bg: 'rgba(34,197,94,0.15)', label: 'NORMAL' };
  if (score < 0.5) return { color: '#eab308', bg: 'rgba(234,179,8,0.15)', label: 'ELEVATED' };
  if (score < 0.7) return { color: '#f97316', bg: 'rgba(249,115,22,0.15)', label: 'HIGH' };
  if (score < 0.85) return { color: '#ef4444', bg: 'rgba(239,68,68,0.15)', label: 'SEVERE' };
  return { color: '#dc2626', bg: 'rgba(220,38,38,0.2)', label: 'CRITICAL' };
}

export default function CISSGauge({ cissScore = 0, severity = 'NORMAL' }) {
  const score = Math.max(0, Math.min(1, cissScore));
  const { color, bg, label } = useMemo(() => getColor(score), [score]);

  // Arc geometry
  const cx = 100, cy = 95;
  const radius = 75;
  const startAngle = Math.PI;
  const endAngle = 2 * Math.PI;
  const sweepAngle = startAngle + (endAngle - startAngle) * score;

  const arcPath = (angle) => {
    const x = cx + radius * Math.cos(angle);
    const y = cy + radius * Math.sin(angle);
    return { x, y };
  };

  const start = arcPath(startAngle);
  const end = arcPath(sweepAngle);
  const largeArc = score > 0.5 ? 1 : 0;

  const bgEnd = arcPath(endAngle);

  return (
    <div className="card ciss-gauge-container">
      <div className="card-header">
        <span className="card-title">Systemic Stress Index</span>
        <span className="card-badge" style={{ background: bg, color }}>
          CISS
        </span>
      </div>
      <div className="gauge-wrapper">
        <svg className="gauge-svg" viewBox="0 0 200 110">
          {/* Background arc */}
          <path
            d={`M ${start.x} ${start.y} A ${radius} ${radius} 0 1 1 ${bgEnd.x} ${bgEnd.y}`}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="10"
            strokeLinecap="round"
          />
          {/* Value arc */}
          {score > 0.001 && (
            <motion.path
              d={`M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`}
              fill="none"
              stroke={color}
              strokeWidth="10"
              strokeLinecap="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.5, ease: 'easeOut' }}
              style={{
                filter: `drop-shadow(0 0 8px ${color}60)`,
              }}
            />
          )}
          {/* Needle dot */}
          <motion.circle
            cx={end.x}
            cy={end.y}
            r="5"
            fill={color}
            animate={{ cx: end.x, cy: end.y }}
            transition={{ duration: 0.3 }}
            style={{ filter: `drop-shadow(0 0 6px ${color})` }}
          />
        </svg>

        <motion.div
          className="gauge-value"
          style={{ color }}
          key={Math.round(score * 100)}
          initial={{ scale: 1.1, opacity: 0.7 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.2 }}
        >
          {(score * 100).toFixed(1)}
          <span style={{ fontSize: '20px', opacity: 0.6 }}>%</span>
        </motion.div>

        <div className="gauge-label">Composite Stress Score</div>

        <AnimatePresence mode="wait">
          <motion.div
            key={label}
            className="gauge-severity"
            style={{ background: bg, color, border: `1px solid ${color}30` }}
            initial={{ y: 5, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -5, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            {label}
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
