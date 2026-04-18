/**
 * AlertBanner — institutional crisis alert bar.
 * Flat, no emoji. Severity is encoded as left-edge color stripe + label.
 */
'use client';

import { motion, AnimatePresence } from 'framer-motion';

export default function AlertBanner({ alert }) {
  if (!alert) return null;
  const isCritical = alert.severity === 'CRITICAL';
  const color = isCritical ? 'var(--red)' : 'var(--orange)';
  const label = isCritical ? 'CRITICAL' : 'HIGH';

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={alert.message || 'alert'}
        className={`alert-banner ${isCritical ? 'critical' : 'high'}`}
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.25, ease: 'easeOut' }}
        style={{ borderLeft: `3px solid ${color}` }}
      >
        <span className="alert-banner-tag" style={{ color, borderColor: color }}>
          {label}
        </span>
        <span className="alert-banner-text">{alert.message}</span>
        <span className="alert-banner-score" style={{ color }}>
          {(alert.score * 100).toFixed(1)}%
        </span>
        {alert.components && (
          <div className="alert-banner-components">
            <span>IF {(alert.components.isolation_forest * 100).toFixed(0)}</span>
            <span>LSTM {(alert.components.lstm_reconstruction * 100).toFixed(0)}</span>
            <span>CISS {(alert.components.ciss * 100).toFixed(0)}</span>
            {alert.components.copula_tail !== undefined && (
              <span>COP {(alert.components.copula_tail * 100).toFixed(0)}</span>
            )}
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
