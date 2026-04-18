'use client';

import { memo } from 'react';
import { motion } from 'framer-motion';

/**
 * VaRPanel — Value-at-Risk & CVaR display panel.
 * Shows Historical VaR, Parametric VaR, Cornish-Fisher VaR,
 * Expected Shortfall (CVaR), and risk regime classification.
 */
const VaRPanel = memo(function VaRPanel({ varMetrics }) {
  const v = varMetrics || {};
  const regime = v.regime || 'NORMAL';

  const regimeColors = {
    NORMAL: { bg: 'rgba(34,197,94,0.1)', border: '#22c55e', text: '#22c55e' },
    ELEVATED: { bg: 'rgba(234,179,8,0.1)', border: '#eab308', text: '#eab308' },
    HIGH: { bg: 'rgba(249,115,22,0.1)', border: '#f97316', text: '#f97316' },
    EXTREME: { bg: 'rgba(239,68,68,0.1)', border: '#ef4444', text: '#ef4444' },
  };
  const rc = regimeColors[regime] || regimeColors.NORMAL;

  const varMethods = [
    { label: 'Historical', value: v.historical_var, desc: 'Empirical quantile' },
    { label: 'Parametric', value: v.parametric_var, desc: 'Normal distribution' },
    { label: 'Cornish-Fisher', value: v.cornish_fisher_var, desc: 'Skew/Kurt adjusted' },
  ];

  const dollarVar = v.dollar_var || 0;
  const dollarCvar = v.dollar_cvar || 0;

  return (
    <div className="var-panel">
      <div className="card-header">
        <span className="card-title">Value-at-Risk</span>
        <span
          className="card-badge"
          style={{ background: rc.bg, color: rc.text, borderColor: rc.border }}
        >
          {regime}
        </span>
      </div>

      {/* Confidence & Window */}
      <div className="var-meta">
        <span>{((v.confidence || 0.99) * 100).toFixed(0)}% Confidence</span>
        <span>{v.window || 0} observations</span>
      </div>

      {/* VaR Methods Grid */}
      <div className="var-methods">
        {varMethods.map((m) => (
          <div key={m.label} className="var-method-card">
            <div className="var-method-label">{m.label}</div>
            <div className="var-method-value">
              {(m.value || 0).toFixed(2)}%
            </div>
            <div className="var-method-desc">{m.desc}</div>
          </div>
        ))}
      </div>

      {/* CVaR (Expected Shortfall) — the key metric */}
      <div className="var-cvar-row">
        <div className="var-cvar-block">
          <div className="var-cvar-label">CVaR (Expected Shortfall)</div>
          <motion.div
            className="var-cvar-value"
            style={{ color: rc.text }}
            key={v.cvar}
            initial={{ scale: 1.1 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.2 }}
          >
            {(v.cvar || 0).toFixed(3)}%
          </motion.div>
        </div>
      </div>

      {/* Dollar VaR */}
      <div className="var-dollar-row">
        <div className="var-dollar-item">
          <span className="var-dollar-label">$ VaR (1M)</span>
          <span className="var-dollar-value">
            ${dollarVar >= 1000 ? (dollarVar / 1000).toFixed(1) + 'K' : dollarVar.toFixed(0)}
          </span>
        </div>
        <div className="var-dollar-item">
          <span className="var-dollar-label">$ CVaR (1M)</span>
          <span className="var-dollar-value" style={{ color: rc.text }}>
            ${dollarCvar >= 1000 ? (dollarCvar / 1000).toFixed(1) + 'K' : dollarCvar.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Distribution Stats */}
      <div className="var-stats-row">
        <div className="var-stat">
          <span className="var-stat-label">Ann. Vol</span>
          <span className="var-stat-value">{(v.volatility_annual || 0).toFixed(1)}%</span>
        </div>
        <div className="var-stat">
          <span className="var-stat-label">Skew</span>
          <span className="var-stat-value">{(v.skewness || 0).toFixed(3)}</span>
        </div>
        <div className="var-stat">
          <span className="var-stat-label">Kurtosis</span>
          <span className="var-stat-value">{(v.kurtosis || 0).toFixed(3)}</span>
        </div>
      </div>
    </div>
  );
});

export default VaRPanel;
