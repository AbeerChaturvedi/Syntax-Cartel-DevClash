/**
 * TailDependenceMatrix — 5x5 λ_L heatmap across market segments.
 * Visualizes the lower-tail dependence coefficients from the t-copula
 * model.  Red-hot cells indicate segments that crash together in the
 * tail — the exact signal Pearson correlation misses.
 */
'use client';

import { useEffect, useState } from 'react';

function tailToColor(v) {
  const x = Math.max(0, Math.min(1, v));
  if (x < 0.15) return `rgba(34, 197, 94, ${0.35 + x * 2})`;
  if (x < 0.35) return `rgba(250, 204, 21, ${0.40 + x})`;
  if (x < 0.60) return `rgba(249, 115, 22, ${0.55 + x * 0.6})`;
  return `rgba(239, 68, 68, ${0.7 + x * 0.3})`;
}

export default function TailDependenceMatrix({ copula }) {
  const [snap, setSnap] = useState(copula || null);

  useEffect(() => {
    if (copula) {
      setSnap(copula);
      return;
    }
    let live = true;
    const fetchOnce = async () => {
      try {
        const base = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
        const r = await fetch(`${base}/api/copula`);
        if (r.ok && live) setSnap(await r.json());
      } catch { /* silent */ }
    };
    fetchOnce();
    const t = setInterval(fetchOnce, 3000);
    return () => { live = false; clearInterval(t); };
  }, [copula]);

  const segments = snap?.segments || [];
  const matrix = snap?.tail_dependence_matrix || [];
  const nu = snap?.nu ?? null;
  const avg = snap?.avg_tail_dependence ?? 0;
  const max = snap?.max_tail_dependence ?? 0;
  const hot = snap?.hot_pair;
  const joint = snap?.joint_crash_prob_1pct ?? 0;
  const warmup = snap?.warmup ?? true;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: 'var(--text-tertiary)',
          textTransform: 'uppercase', letterSpacing: '0.05em',
        }}>
          Tail Dependence (t-Copula λL)
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)',
        }}>
          ν={nu ?? '…'}
        </span>
      </div>

      {warmup ? (
        <div style={{
          padding: '24px 12px', textAlign: 'center',
          fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)',
        }}>
          Warming up copula — need 50+ residuals per segment.
        </div>
      ) : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 10, margin: '0 auto' }}>
              <thead>
                <tr>
                  <th></th>
                  {segments.map((s) => (
                    <th key={s} style={{
                      color: 'var(--text-tertiary)', padding: '4px 6px',
                      writingMode: 'vertical-lr', transform: 'rotate(180deg)',
                      fontWeight: 600, textTransform: 'uppercase',
                    }}>{s.slice(0, 3)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.map((row, i) => (
                  <tr key={i}>
                    <td style={{
                      color: 'var(--text-tertiary)', padding: '3px 8px',
                      textAlign: 'right', fontWeight: 600, textTransform: 'uppercase',
                    }}>{segments[i]?.slice(0, 3)}</td>
                    {row.map((v, j) => (
                      <td
                        key={j}
                        title={`λL(${segments[i]},${segments[j]}) = ${v.toFixed(3)}`}
                        style={{
                          background: tailToColor(v),
                          width: 36, height: 22,
                          textAlign: 'center', color: i === j ? 'rgba(0,0,0,0.35)' : '#0b0d13',
                          fontSize: 9, fontWeight: 700,
                        }}
                      >{v.toFixed(2)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{
            display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
            marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 10,
          }}>
            <div>
              <div style={{ color: 'var(--text-muted)' }}>avg λL</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: avg > 0.4 ? '#ef4444' : avg > 0.2 ? '#f97316' : '#22c55e' }}>
                {avg.toFixed(3)}
              </div>
            </div>
            <div>
              <div style={{ color: 'var(--text-muted)' }}>max λL</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: max > 0.5 ? '#ef4444' : max > 0.3 ? '#f97316' : '#22c55e' }}>
                {max.toFixed(3)}
              </div>
            </div>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ color: 'var(--text-muted)' }}>hot pair · joint-crash P(1%)</div>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' }}>
                {hot ? `${hot[0]} ↔ ${hot[1]}` : '—'} · {(joint * 100).toFixed(3)}%
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
