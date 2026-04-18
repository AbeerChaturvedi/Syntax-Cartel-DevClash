/**
 * AlertBanner — Animated crisis alert notification bar.
 * Slides in when anomaly scores cross thresholds.
 */
'use client';

import { motion, AnimatePresence } from 'framer-motion';

export default function AlertBanner({ alert }) {
  if (!alert) return null;

  const isHigh = alert.severity === 'HIGH';
  const isCritical = alert.severity === 'CRITICAL';
  const color = isCritical ? '#ef4444' : '#f97316';

  return (
    <AnimatePresence>
      <motion.div
        className={`alert-banner ${isCritical ? 'critical' : 'high'}`}
        initial={{ opacity: 0, y: -20, height: 0 }}
        animate={{ opacity: 1, y: 0, height: 'auto' }}
        exit={{ opacity: 0, y: -20, height: 0 }}
        transition={{ duration: 0.3, ease: 'easeOut' }}
      >
        <span className="alert-banner-icon">
          {isCritical ? '🚨' : '⚠️'}
        </span>
        <span className="alert-banner-text" style={{ color }}>
          {alert.message}
        </span>
        <span className="alert-banner-score" style={{ color }}>
          {(alert.score * 100).toFixed(1)}%
        </span>
        {alert.components && (
          <div style={{
            display: 'flex', gap: '12px', fontSize: '10px',
            fontFamily: 'var(--font-mono)', color: 'var(--text-tertiary)',
          }}>
            <span>IF: {(alert.components.isolation_forest * 100).toFixed(0)}%</span>
            <span>LSTM: {(alert.components.lstm_reconstruction * 100).toFixed(0)}%</span>
            <span>CISS: {(alert.components.ciss * 100).toFixed(0)}%</span>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
}
