/**
 * SRISKPanel — System-wide SRISK (Systemic Risk Measure) visualization.
 * Shows aggregate capital shortfall across all tracked financial institutions.
 * 
 * SRISK = k*D - (1-k)*(1-LRMES)*E
 * Positive SRISK = institution needs capital to survive a crisis.
 */
'use client';

import { motion } from 'framer-motion';

function getStatusStyle(status) {
  switch (status) {
    case 'HEALTHY':  return { color: '#22c55e', bg: 'rgba(34,197,94,0.15)', glow: 'rgba(34,197,94,0.3)' };
    case 'ELEVATED': return { color: '#eab308', bg: 'rgba(234,179,8,0.15)', glow: 'rgba(234,179,8,0.3)' };
    case 'WARNING':  return { color: '#f97316', bg: 'rgba(249,115,22,0.15)', glow: 'rgba(249,115,22,0.3)' };
    case 'CRITICAL': return { color: '#ef4444', bg: 'rgba(239,68,68,0.15)', glow: 'rgba(239,68,68,0.4)' };
    default:         return { color: '#94a3b8', bg: 'rgba(148,163,184,0.1)', glow: 'rgba(148,163,184,0.1)' };
  }
}

function SRISKBar({ institution, maxSRISK }) {
  const pct = maxSRISK > 0 ? (institution.srisk_bn / maxSRISK) * 100 : 0;
  const statusStyle = getStatusStyle(institution.status);

  return (
    <div className="srisk-bar-row">
      <div className="srisk-bar-label">
        <span className="srisk-ticker">{institution.ticker}</span>
        <span className="srisk-name">{institution.name}</span>
      </div>
      <div className="srisk-bar-track">
        <motion.div
          className="srisk-bar-fill"
          style={{ background: `linear-gradient(90deg, ${statusStyle.color}80, ${statusStyle.color})` }}
          animate={{ width: `${Math.min(100, pct)}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <div className="srisk-bar-value" style={{ color: statusStyle.color }}>
        ${institution.srisk_bn?.toFixed(1)}B
      </div>
    </div>
  );
}

export default function SRISKPanel({ systemSRISK = {}, merton = [] }) {
  const totalBn = systemSRISK.total_bn || 0;
  const status = systemSRISK.status || 'HEALTHY';
  const style = getStatusStyle(status);
  const maxSRISK = Math.max(...merton.map(m => m.srisk_bn || 0), 1);

  // Sort by SRISK descending
  const sorted = [...merton].sort((a, b) => (b.srisk_bn || 0) - (a.srisk_bn || 0));

  return (
    <div className="card srisk-panel">
      <div className="card-header">
        <span className="card-title">System SRISK</span>
        <span className="card-badge" style={{ background: style.bg, color: style.color }}>
          {status}
        </span>
      </div>

      {/* Aggregate SRISK */}
      <div className="srisk-aggregate" style={{ borderColor: `${style.color}30` }}>
        <div className="srisk-aggregate-label">Aggregate Capital Shortfall</div>
        <motion.div
          className="srisk-aggregate-value"
          style={{ color: style.color }}
          key={Math.round(totalBn)}
          initial={{ scale: 1.05 }}
          animate={{ scale: 1 }}
          transition={{ duration: 0.2 }}
        >
          ${totalBn.toFixed(1)}
          <span className="srisk-unit">B</span>
        </motion.div>
        <div className="srisk-aggregate-desc">
          Expected capital needed across {merton.length} institutions during market stress
        </div>
      </div>

      {/* Per-institution breakdown */}
      <div className="srisk-bars">
        {sorted.map((inst) => (
          <SRISKBar
            key={inst.ticker}
            institution={inst}
            maxSRISK={maxSRISK}
          />
        ))}
      </div>

      {/* LRMES indicator */}
      {merton.length > 0 && (
        <div className="srisk-lrmes-row">
          <span className="srisk-lrmes-label">Avg LRMES</span>
          <span className="srisk-lrmes-value">
            {(merton.reduce((s, m) => s + (m.lrmes || 0), 0) / merton.length * 100).toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}
