/**
 * CorrelationHeatmap — Cross-asset correlation matrix visualization.
 * Uses Canvas for GPU-accelerated rendering.
 */
'use client';

import { useRef, useEffect, useMemo } from 'react';

const LABELS = [
  'SPY', 'QQQ', 'DIA', 'IWM', 'XLF', 'JPM', 'GS', 'BAC', 'C', 'MS',
  'EUR', 'GBP', 'JPY', 'US10', 'US2', 'SOFR', 'BTC', 'ETH'
];

function correlationToColor(value) {
  // Map [-1, 1] to color: blue → dark → red
  const v = Math.max(-1, Math.min(1, value));
  if (v >= 0) {
    const r = Math.round(99 + 140 * v);
    const g = Math.round(102 - 60 * v);
    const b = Math.round(241 - 200 * v);
    return `rgb(${r}, ${g}, ${b})`;
  } else {
    const absV = Math.abs(v);
    const r = Math.round(34 + 25 * absV);
    const g = Math.round(197 - 130 * absV);
    const b = Math.round(94 + 50 * absV);
    return `rgb(${r}, ${g}, ${b})`;
  }
}

export default function CorrelationHeatmap({ matrix = [], avgCorrelation = 0 }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !matrix.length) return;

    const ctx = canvas.getContext('2d');
    const n = Math.min(matrix.length, LABELS.length);
    const cellSize = 14;
    const labelSpace = 30;
    const totalSize = labelSpace + n * cellSize;

    canvas.width = totalSize * 2;  // 2x for retina
    canvas.height = totalSize * 2;
    canvas.style.width = `${totalSize}px`;
    canvas.style.height = `${totalSize}px`;
    ctx.scale(2, 2);

    // Clear
    ctx.clearRect(0, 0, totalSize, totalSize);

    // Draw cells
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        const val = matrix[i]?.[j] ?? 0;
        ctx.fillStyle = correlationToColor(val);
        ctx.globalAlpha = 0.7 + 0.3 * Math.abs(val);
        ctx.fillRect(labelSpace + j * cellSize, labelSpace + i * cellSize, cellSize - 1, cellSize - 1);
      }
    }

    // Draw labels
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#64748b';
    ctx.font = '7px "JetBrains Mono", monospace';
    ctx.textAlign = 'right';
    for (let i = 0; i < n; i++) {
      // Row labels
      ctx.save();
      ctx.textAlign = 'right';
      ctx.fillText(LABELS[i] || '', labelSpace - 3, labelSpace + i * cellSize + cellSize / 2 + 3);
      ctx.restore();

      // Column labels
      ctx.save();
      ctx.translate(labelSpace + i * cellSize + cellSize / 2, labelSpace - 3);
      ctx.rotate(-Math.PI / 4);
      ctx.textAlign = 'right';
      ctx.fillText(LABELS[i] || '', 0, 0);
      ctx.restore();
    }
  }, [matrix]);

  const corrColor = avgCorrelation > 0.6 ? '#ef4444' : avgCorrelation > 0.4 ? '#f97316' : avgCorrelation > 0.25 ? '#eab308' : '#22c55e';

  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: '8px',
      }}>
        <span style={{
          fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)',
          textTransform: 'uppercase', letterSpacing: '0.05em',
        }}>
          Cross-Asset Correlation
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: '13px', fontWeight: 700, color: corrColor,
        }}>
          ρ̄ = {avgCorrelation.toFixed(3)}
        </span>
      </div>

      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <canvas ref={canvasRef} style={{ imageRendering: 'pixelated' }} />
      </div>

      {/* Color scale legend */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        marginTop: '8px', justifyContent: 'center',
      }}>
        <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>-1.0</span>
        <div style={{
          width: '120px', height: '6px', borderRadius: '3px',
          background: 'linear-gradient(90deg, #3fa66b, #1a1a1a, #ff8c00, #b91c1c)',
        }} />
        <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>+1.0</span>
      </div>
    </div>
  );
}
