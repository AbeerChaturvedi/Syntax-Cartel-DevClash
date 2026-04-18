/**
 * StressTestButton — Triggers crisis simulation via backend API.
 * Includes preset scenarios + custom activation with visual feedback.
 */
'use client';

import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const PRESETS = [
  { id: 'lehman_2008', label: '2008 Lehman', tag: 'CREDIT', desc: 'Credit contagion, interbank freeze', color: 'var(--red)' },
  { id: 'covid_2020', label: '2020 COVID', tag: 'LIQUID', desc: 'Liquidity crisis, VIX spike to 82', color: 'var(--orange)' },
  { id: 'svb_2023', label: '2023 SVB', tag: 'RATES', desc: 'Regional bank run, rate shock', color: 'var(--yellow)' },
  { id: 'flash_crash', label: 'Flash Crash', tag: 'HFT', desc: 'HFT liquidity vacuum, 6-min drop', color: 'var(--accent)' },
];

export default function StressTestButton({ crisisMode = false }) {
  const [loading, setLoading] = useState(false);
  const [activePreset, setActivePreset] = useState(null);
  const [showPresets, setShowPresets] = useState(false);

  const activatePreset = useCallback(async (presetId) => {
    setLoading(true);
    setActivePreset(presetId);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      await fetch(`${API_URL}/api/stress-test/preset`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: presetId }),
        signal: controller.signal,
      });
      setShowPresets(false);
    } catch (e) {
      console.error('Failed to activate preset:', e);
    } finally {
      clearTimeout(timeout);
    }
    setLoading(false);
  }, []);

  const activateCustom = useCallback(async () => {
    setLoading(true);
    setActivePreset('custom');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      await fetch(`${API_URL}/api/stress-test/activate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ intensity: 0.85, duration_seconds: 45 }),
        signal: controller.signal,
      });
      setShowPresets(false);
    } catch (e) {
      console.error('Failed to activate stress test:', e);
    } finally {
      clearTimeout(timeout);
    }
    setLoading(false);
  }, []);

  const deactivateCrisis = useCallback(async () => {
    setLoading(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      await fetch(`${API_URL}/api/stress-test/deactivate`, {
        method: 'POST',
        signal: controller.signal,
      });
    } catch (e) {
      console.error('Failed to deactivate stress test:', e);
    } finally {
      clearTimeout(timeout);
    }
    setLoading(false);
    setActivePreset(null);
  }, []);

  if (crisisMode) {
    const preset = PRESETS.find(p => p.id === activePreset);
    return (
      <div className="stress-test-wrapper">
        <div className="stress-test-active-row">
          <motion.button
            className="stress-test-btn active"
            disabled
            animate={{ scale: [1, 1.02, 1] }}
            transition={{ repeat: Infinity, duration: 1.5 }}
          >
            {preset ? `${preset.label}` : 'CRISIS'} · ACTIVE
          </motion.button>
          <button
            className="deactivate-btn"
            onClick={deactivateCrisis}
            disabled={loading}
          >
            Restore Normal
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="stress-test-wrapper">
      <div className="stress-test-row">
        <motion.button
          className="stress-test-btn"
          onClick={() => setShowPresets(!showPresets)}
          disabled={loading}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {loading ? (
            <>
              <span className="loading-spinner" style={{ width: '14px', height: '14px', borderWidth: '2px' }} />
              Injecting...
            </>
          ) : (
            <>Simulate Crisis</>
          )}
        </motion.button>
      </div>

      <AnimatePresence>
        {showPresets && (
          <motion.div
            className="crisis-presets-grid"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
          >
            {PRESETS.map((preset) => (
              <motion.button
                key={preset.id}
                className="crisis-preset-btn"
                style={{ '--preset-color': preset.color }}
                onClick={() => activatePreset(preset.id)}
                disabled={loading}
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
              >
                <span className="preset-tag" style={{ color: preset.color }}>{preset.tag}</span>
                <span className="preset-label">{preset.label}</span>
                <span className="preset-desc">{preset.desc}</span>
              </motion.button>
            ))}
            <motion.button
              className="crisis-preset-btn custom"
              onClick={activateCustom}
              disabled={loading}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
            >
              <span className="preset-tag" style={{ color: 'var(--accent)' }}>CUSTOM</span>
              <span className="preset-label">Custom</span>
              <span className="preset-desc">85% intensity, 45s</span>
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
