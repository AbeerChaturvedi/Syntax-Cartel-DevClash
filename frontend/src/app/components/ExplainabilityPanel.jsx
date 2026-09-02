/**
 * ExplainabilityPanel — Shows WHY the model flagged an anomaly.
 * Feature importance bars + CISS segment breakdown.
 */
'use client';

import { motion } from 'framer-motion';

// Assets in the exact alphabetical order used by state_builder.py
// Backend now sends fully-labeled feature names ("BAC Return") so the
// UI just displays them as-is. FEATURE_LABELS kept as a fallback for
// any leftover `feature_N` keys during the deploy transition.
const TRACKED_ASSETS = [
  'BAC', 'BTCUSD', 'C', 'DIA', 'ETHUSD',
  'EURUSD', 'GBPUSD', 'GS', 'IWM', 'JPM',
  'MS', 'QQQ', 'SPY', 'USDJPY', 'XLF',
];
const FEATURE_NAMES = ['Return', 'Volatility', 'Mean Return', 'Max |Return|'];

// Fallback label map for the legacy `feature_N` key format
const FEATURE_LABELS = {};
TRACKED_ASSETS.forEach((asset, ai) => {
  FEATURE_NAMES.forEach((feat, fi) => {
    FEATURE_LABELS[`feature_${ai * 4 + fi}`] = `${asset} ${feat}`;
  });
});


function prettyLabel(key) {
  // If the key already contains a space (e.g. "BAC Return"), it's a
  // fully-labeled backend name — use it as-is.
  if (key.includes(' ')) return key;
  return FEATURE_LABELS[key] || key.replace('feature_', 'F');
}

function FeatureBar({ name, value, maxValue }) {
  const pct = maxValue > 0 ? (value / maxValue) * 100 : 0;

  return (
    <div className="feature-bar">
      <span className="feature-name" title={name}>{prettyLabel(name)}</span>
      <div className="feature-bar-track">
        <motion.div
          className="feature-bar-fill"
          animate={{ width: `${Math.min(100, pct)}%` }}
          transition={{ duration: 0.4, ease: 'easeOut' }}
        />
      </div>
      <span className="feature-value">{value.toFixed(4)}</span>
    </div>
  );
}

function CISSBreakdown({ breakdown = {} }) {
  const segments = breakdown.segments || {};
  const entries = Object.entries(segments);
  if (entries.length === 0) return null;

  return (
    <div style={{ marginTop: '16px' }}>
      <div style={{
        fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)',
        textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px',
      }}>
        CISS Segment Scores
      </div>
      {entries.map(([name, data]) => {
        const cdfPct = (data.cdf_score || 0) * 100;
        const color = cdfPct > 70 ? '#ef4444' : cdfPct > 50 ? '#f97316' : cdfPct > 30 ? '#eab308' : '#22c55e';
        return (
          <div key={name} style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            marginBottom: '6px', fontSize: '12px',
          }}>
            <span style={{
              width: '80px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)',
              fontSize: '10px', textTransform: 'capitalize',
            }}>
              {name}
            </span>
            <div style={{
              flex: 1, height: '4px', background: 'var(--bg-primary)',
              borderRadius: '9999px', overflow: 'hidden',
            }}>
              <motion.div
                style={{ height: '100%', background: color, borderRadius: '9999px' }}
                animate={{ width: `${cdfPct}%` }}
                transition={{ duration: 0.3 }}
              />
            </div>
            <span style={{
              width: '40px', textAlign: 'right', fontFamily: 'var(--font-mono)',
              fontSize: '10px', color,
            }}>
              {cdfPct.toFixed(0)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

export default function ExplainabilityPanel({ featureImportance = {}, cissBreakdown = {} }) {
  const entries = Object.entries(featureImportance);
  const maxValue = entries.length > 0 ? Math.max(...entries.map(([, v]) => v)) : 1;
  const topFeatures = entries.slice(0, 8);

  return (
    <div className="explainability-section">
      <div style={{
        fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)',
        textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px',
        display: 'flex', alignItems: 'center', gap: '8px',
      }}>
        Feature Attribution
      </div>

      {topFeatures.length > 0 ? (
        topFeatures.map(([name, value]) => (
          <FeatureBar key={name} name={name} value={value} maxValue={maxValue} />
        ))
      ) : (
        <div style={{ color: 'var(--text-muted)', fontSize: '12px', padding: '16px 0' }}>
          Accumulating feature data...
        </div>
      )}

      <CISSBreakdown breakdown={cissBreakdown} />
    </div>
  );
}
