/**
 * CISSGauge — Composite Indicator of Systemic Stress.
 * Institutional readout: flat colors, no glow, slow transitions
 * tuned to the 2s display flush so the needle does not whipsaw.
 */
'use client';

import { useMemo } from 'react';

function getColor(score) {
  if (score < 0.30) return { color: '#3fa66b', label: 'NORMAL' };
  if (score < 0.50) return { color: '#c9a227', label: 'ELEVATED' };
  if (score < 0.70) return { color: '#d97706', label: 'HIGH' };
  if (score < 0.85) return { color: '#c2410c', label: 'SEVERE' };
  return { color: '#b91c1c', label: 'CRITICAL' };
}

export default function CISSGauge({ cissScore = 0, severity = 'NORMAL' }) {
  const score = Math.max(0, Math.min(1, Number(cissScore) || 0));
  const { color, label } = useMemo(() => getColor(score), [score]);

  const cx = 100;
  const cy = 100;
  const radius = 78;
  const arcLen = Math.PI * radius;
  const valueDash = arcLen * score;

  const startX = cx - radius;
  const endX = cx + radius;

  // Needle (single tick) along arc
  const needleAngle = Math.PI * (1 - score);
  const needleX = cx + radius * Math.cos(needleAngle);
  const needleY = cy - radius * Math.sin(needleAngle);

  const bgArc = `M ${startX} ${cy} A ${radius} ${radius} 0 0 1 ${endX} ${cy}`;

  return (
    <div className="card ciss-gauge-container">
      <div className="card-header">
        <span className="card-title">Systemic Stress Index</span>
        <span className="card-badge">CISS</span>
      </div>

      <div className="gauge-wrapper">
        <svg className="gauge-svg" viewBox="0 0 200 120" aria-label="CISS gauge">
          {/* Tick marks at 0, 25, 50, 75, 100 */}
          {[0, 0.25, 0.5, 0.75, 1].map((t) => {
            const a = Math.PI * (1 - t);
            const ix = cx + (radius - 10) * Math.cos(a);
            const iy = cy - (radius - 10) * Math.sin(a);
            const ox = cx + (radius + 4) * Math.cos(a);
            const oy = cy - (radius + 4) * Math.sin(a);
            return (
              <line
                key={t}
                x1={ix}
                y1={iy}
                x2={ox}
                y2={oy}
                stroke="#2a2a2a"
                strokeWidth="1"
              />
            );
          })}

          {/* Background arc */}
          <path
            d={bgArc}
            fill="none"
            stroke="#1a1a1a"
            strokeWidth="10"
            strokeLinecap="butt"
          />

          {/* Value arc — butt caps + slow transition kill the visual jitter */}
          {score > 0.005 && (
            <path
              d={bgArc}
              fill="none"
              stroke={color}
              strokeWidth="10"
              strokeLinecap="butt"
              strokeDasharray={`${valueDash} ${arcLen}`}
              style={{ transition: 'stroke-dasharray 1.4s ease-out, stroke 1.4s ease-out' }}
            />
          )}

          {/* Needle marker — small filled square, no glow */}
          <rect
            x={needleX - 3}
            y={needleY - 3}
            width="6"
            height="6"
            fill={color}
            style={{ transition: 'x 1.4s ease-out, y 1.4s ease-out, fill 1.4s ease-out' }}
          />

          {/* Hub */}
          <circle cx={cx} cy={cy} r="2.5" fill="#3a3a3a" />
        </svg>

        <div className="gauge-value" style={{ color }}>
          {(score * 100).toFixed(1)}
          <span className="gauge-value-pct">%</span>
        </div>

        <div className="gauge-label">Composite Stress Score · 1-min median</div>

        <div className="gauge-severity" style={{ color, borderColor: color }}>
          {label}
        </div>
      </div>
    </div>
  );
}
