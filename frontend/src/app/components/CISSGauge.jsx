/**
 * CISSGauge — Composite Indicator of Systemic Stress
 * SVG arc gauge with smooth CSS transitions.
 */
'use client';

import { useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

function getColor(score) {
  if (score < 0.3) return { color: '#4ade80', bg: 'rgba(74,222,128,0.10)', label: 'NORMAL' };
  if (score < 0.5) return { color: '#facc15', bg: 'rgba(250,204,21,0.10)', label: 'ELEVATED' };
  if (score < 0.7) return { color: '#fb923c', bg: 'rgba(251,146,60,0.10)', label: 'HIGH' };
  if (score < 0.85) return { color: '#f87171', bg: 'rgba(248,113,113,0.10)', label: 'SEVERE' };
  return { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', label: 'CRITICAL' };
}

export default function CISSGauge({ cissScore = 0, severity = 'NORMAL' }) {
  const score = Math.max(0, Math.min(1, cissScore));
  const { color, bg, label } = useMemo(() => getColor(score), [score]);

  // Arc geometry — semicircle opening upward
  const cx = 100, cy = 95;
  const radius = 75;
  // Total arc length for stroke-dasharray
  const arcLen = Math.PI * radius; // half circumference
  const valueDash = arcLen * score;

  // Start (left) and end (right) of the semicircle
  const startX = cx - radius;
  const startY = cy;
  const endX = cx + radius;
  const endY = cy;

  // Needle position along the arc
  const needleAngle = Math.PI * (1 - score); // π (left) → 0 (right)
  const needleX = cx + radius * Math.cos(needleAngle);
  const needleY = cy - radius * Math.sin(needleAngle);

  // Background arc path (top semicircle, left to right)
  const bgArc = `M ${startX} ${startY} A ${radius} ${radius} 0 0 1 ${endX} ${endY}`;

  return (
    <div className="card ciss-gauge-container">
      <div className="card-header">
        <span className="card-title">Systemic Stress Index</span>
        <span className="card-badge" style={{ background: bg, color }}>
          CISS
        </span>
      </div>
      <div className="gauge-wrapper">
        <svg className="gauge-svg" viewBox="0 0 200 115">
          {/* Tick marks */}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const a = Math.PI * (1 - t);
            const ix = cx + (radius - 8) * Math.cos(a);
            const iy = cy - (radius - 8) * Math.sin(a);
            const ox = cx + (radius + 4) * Math.cos(a);
            const oy = cy - (radius + 4) * Math.sin(a);
            return (
              <line key={t} x1={ix} y1={iy} x2={ox} y2={oy}
                stroke="rgba(148,163,184,0.25)" strokeWidth="1" />
            );
          })}
          {/* Background arc */}
          <path
            d={bgArc}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="8"
            strokeLinecap="round"
          />
          {/* Value arc — uses dasharray for smooth transitions */}
          {score > 0.001 && (
            <path
              d={bgArc}
              fill="none"
              stroke={color}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={`${valueDash} ${arcLen}`}
              style={{
                transition: 'stroke-dasharray 0.4s ease, stroke 0.4s ease',
                filter: `drop-shadow(0 0 6px ${color}40)`,
              }}
            />
          )}
          {/* Needle dot */}
          <circle
            cx={needleX}
            cy={needleY}
            r="4"
            fill={color}
            style={{
              transition: 'cx 0.4s ease, cy 0.4s ease, fill 0.4s ease',
              filter: `drop-shadow(0 0 4px ${color})`,
            }}
          />
          {/* Center dot */}
          <circle cx={cx} cy={cy} r="2" fill="rgba(148,163,184,0.3)" />
        </svg>

        <div
          className="gauge-value"
          style={{ color, transition: 'color 0.4s ease' }}
        >
          {(score * 100).toFixed(1)}
          <span style={{ fontSize: '18px', opacity: 0.5 }}>%</span>
        </div>

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
