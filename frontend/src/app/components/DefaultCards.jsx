/**
 * DefaultCards — Merton Distance-to-Default cards for financial institutions.
 * Shows DD, PD, and risk status with color-coded indicators.
 */
'use client';

import { motion, AnimatePresence } from 'framer-motion';

function getStatusStyle(status) {
  switch (status) {
    case 'HEALTHY':  return { color: '#22c55e', bg: 'rgba(34,197,94,0.15)', border: 'rgba(34,197,94,0.2)' };
    case 'WATCH':    return { color: '#eab308', bg: 'rgba(234,179,8,0.15)', border: 'rgba(234,179,8,0.2)' };
    case 'WARNING':  return { color: '#f97316', bg: 'rgba(249,115,22,0.15)', border: 'rgba(249,115,22,0.2)' };
    case 'CRITICAL': return { color: '#ef4444', bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.2)' };
    default:         return { color: '#94a3b8', bg: 'rgba(148,163,184,0.1)', border: 'rgba(148,163,184,0.1)' };
  }
}

function DefaultCard({ data, index }) {
  const style = getStatusStyle(data.status);
  
  return (
    <motion.div
      className="default-card"
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.05, duration: 0.3 }}
      style={{ borderColor: data.status === 'CRITICAL' ? 'rgba(239,68,68,0.3)' : undefined }}
    >
      <div
        className="default-card-icon"
        style={{
          background: style.bg,
          color: style.color,
          border: `1px solid ${style.border}`,
        }}
      >
        {data.ticker?.slice(0, 2)}
      </div>

      <div className="default-card-info">
        <div className="default-card-name">{data.name}</div>
        <div className="default-card-ticker">{data.ticker}</div>
      </div>

      <div className="default-card-metrics">
        <div className="default-card-dd" style={{ color: style.color }}>
          {data.distance_to_default?.toFixed(2)}
          <span style={{ fontSize: '10px', opacity: 0.6, marginLeft: '2px' }}>DD</span>
        </div>
        <div className="default-card-pd">
          PD: {(data.prob_default * 100).toFixed(3)}%
        </div>
        <span
          className="default-card-status"
          style={{ background: style.bg, color: style.color, border: `1px solid ${style.border}` }}
        >
          {data.status}
        </span>
      </div>
    </motion.div>
  );
}

export default function DefaultCards({ merton = [] }) {
  return (
    <div className="card default-cards-container">
      <div className="card-header">
        <span className="card-title">Distance to Default</span>
        <span className="card-badge">MERTON</span>
      </div>

      <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '12px' }}>
        Structural credit risk — lower DD = higher default probability
      </div>

      <AnimatePresence>
        {merton.map((inst, i) => (
          <DefaultCard key={inst.ticker} data={inst} index={i} />
        ))}
      </AnimatePresence>

      {merton.length === 0 && (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)', fontSize: '13px' }}>
          Calibrating Merton model...
        </div>
      )}

      {/* Legend */}
      <div style={{
        display: 'flex', gap: '12px', marginTop: '16px', paddingTop: '12px',
        borderTop: '1px solid var(--border-primary)', flexWrap: 'wrap',
      }}>
        {['HEALTHY', 'WATCH', 'WARNING', 'CRITICAL'].map(status => {
          const s = getStatusStyle(status);
          return (
            <div key={status} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <div style={{
                width: '8px', height: '8px', borderRadius: '2px',
                background: s.color,
              }} />
              <span style={{ fontSize: '9px', color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.03em' }}>
                {status}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
