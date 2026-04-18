/**
 * PortfolioBuilder — Custom portfolio VaR/CVaR calculator.
 * User inputs tickers + weights, computes portfolio VaR against
 * the live ensemble pipeline via POST /api/var/portfolio.
 */
'use client';

import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const DEFAULT_PORTFOLIO = [
  { ticker: 'SPY', weight: 0.40 },
  { ticker: 'QQQ', weight: 0.20 },
  { ticker: 'US10Y', weight: 0.15 },
  { ticker: 'BTCUSD', weight: 0.10 },
  { ticker: 'EURUSD', weight: 0.10 },
  { ticker: 'XLF', weight: 0.05 },
];

const QUICK_PORTFOLIOS = [
  {
    name: '60/40 Classic',
    items: [
      { ticker: 'SPY', weight: 0.60 },
      { ticker: 'US10Y', weight: 0.40 },
    ],
  },
  {
    name: 'Tech Heavy',
    items: [
      { ticker: 'QQQ', weight: 0.50 },
      { ticker: 'SPY', weight: 0.30 },
      { ticker: 'BTCUSD', weight: 0.20 },
    ],
  },
  {
    name: 'Bank Exposure',
    items: [
      { ticker: 'JPM', weight: 0.25 },
      { ticker: 'GS', weight: 0.20 },
      { ticker: 'BAC', weight: 0.20 },
      { ticker: 'C', weight: 0.15 },
      { ticker: 'MS', weight: 0.20 },
    ],
  },
];

function formatDollar(v) {
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

export default function PortfolioBuilder() {
  const [rows, setRows] = useState(DEFAULT_PORTFOLIO);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [notional, setNotional] = useState(1000000);
  const [confidence, setConfidence] = useState(0.99);

  const totalWeight = rows.reduce((s, r) => s + (r.weight || 0), 0);

  const addRow = useCallback(() => {
    setRows(prev => [...prev, { ticker: '', weight: 0 }]);
  }, []);

  const removeRow = useCallback((idx) => {
    setRows(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const updateRow = useCallback((idx, field, value) => {
    setRows(prev => prev.map((r, i) => i === idx ? { ...r, [field]: value } : r));
  }, []);

  const loadQuick = useCallback((items) => {
    setRows(items.map(i => ({ ...i })));
    setResult(null);
  }, []);

  const compute = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const weights = {};
      rows.forEach(r => {
        if (r.ticker && r.weight > 0) {
          weights[r.ticker.toUpperCase()] = r.weight;
        }
      });
      const res = await fetch(`${API_URL}/api/var/portfolio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weights, notional, confidence }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Error ${res.status}`);
      }
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    }
    setLoading(false);
  }, [rows, notional, confidence]);

  return (
    <div className="card portfolio-builder-card">
      <div className="card-header">
        <span className="card-title">Portfolio Risk Builder</span>
        <span className="card-badge" style={{ background: 'rgba(6,182,212,0.15)', color: '#06b6d4' }}>
          VaR Engine
        </span>
      </div>

      {/* Quick presets */}
      <div className="portfolio-quick-row">
        {QUICK_PORTFOLIOS.map((p) => (
          <button
            key={p.name}
            className="portfolio-quick-btn"
            onClick={() => loadQuick(p.items)}
          >
            {p.name}
          </button>
        ))}
      </div>

      {/* Portfolio table */}
      <div className="portfolio-table-wrap">
        <table className="portfolio-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Weight</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <input
                    type="text"
                    className="portfolio-input"
                    value={r.ticker}
                    onChange={(e) => updateRow(i, 'ticker', e.target.value.toUpperCase())}
                    placeholder="SPY"
                    maxLength={8}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    className="portfolio-input weight-input"
                    value={r.weight}
                    onChange={(e) => updateRow(i, 'weight', parseFloat(e.target.value) || 0)}
                    step="0.05"
                    min="0"
                    max="1"
                  />
                </td>
                <td>
                  <button className="portfolio-remove-btn" onClick={() => removeRow(i)}>×</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="portfolio-controls-row">
          <button className="portfolio-add-btn" onClick={addRow}>+ Add Position</button>
          <span className="portfolio-weight-total" style={{
            color: Math.abs(totalWeight - 1.0) < 0.01 ? 'var(--green)' : 'var(--red)',
          }}>
            Σ = {(totalWeight * 100).toFixed(0)}%
          </span>
        </div>
      </div>

      {/* Notional + confidence */}
      <div className="portfolio-params-row">
        <div className="portfolio-param">
          <label>Notional ($)</label>
          <input
            type="number"
            className="portfolio-input"
            value={notional}
            onChange={(e) => setNotional(parseFloat(e.target.value) || 1e6)}
          />
        </div>
        <div className="portfolio-param">
          <label>Confidence</label>
          <select className="portfolio-select" value={confidence} onChange={(e) => setConfidence(parseFloat(e.target.value))}>
            <option value={0.95}>95%</option>
            <option value={0.99}>99%</option>
            <option value={0.999}>99.9%</option>
          </select>
        </div>
      </div>

      {/* Compute button */}
      <motion.button
        className="portfolio-compute-btn"
        onClick={compute}
        disabled={loading || rows.length === 0}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
      >
        {loading ? (
          <>
            <span className="loading-spinner" style={{ width: 14, height: 14, borderWidth: 2 }} />
            Computing...
          </>
        ) : (
          '⚡ Compute Portfolio VaR'
        )}
      </motion.button>

      {/* Error */}
      {error && (
        <div className="portfolio-error">{error}</div>
      )}

      {/* Results */}
      <AnimatePresence>
        {result && !error && (
          <motion.div
            className="portfolio-results"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
          >
            <div className="portfolio-results-grid">
              <div className="portfolio-result-item">
                <div className="portfolio-result-label">Historical VaR</div>
                <div className="portfolio-result-value" style={{ color: '#6366f1' }}>
                  {result.historical_var?.toFixed(4) || '—'}%
                </div>
              </div>
              <div className="portfolio-result-item">
                <div className="portfolio-result-label">Parametric VaR</div>
                <div className="portfolio-result-value" style={{ color: '#a855f7' }}>
                  {result.parametric_var?.toFixed(4) || '—'}%
                </div>
              </div>
              <div className="portfolio-result-item">
                <div className="portfolio-result-label">Cornish-Fisher VaR</div>
                <div className="portfolio-result-value" style={{ color: '#06b6d4' }}>
                  {result.cornish_fisher_var?.toFixed(4) || '—'}%
                </div>
              </div>
              <div className="portfolio-result-item">
                <div className="portfolio-result-label">CVaR (Exp. Shortfall)</div>
                <div className="portfolio-result-value" style={{ color: '#ef4444' }}>
                  {result.cvar?.toFixed(4) || '—'}%
                </div>
              </div>
              <div className="portfolio-result-item highlight">
                <div className="portfolio-result-label">Dollar VaR</div>
                <div className="portfolio-result-value" style={{ color: '#f97316', fontSize: 22 }}>
                  {result.dollar_var ? formatDollar(result.dollar_var) : '—'}
                </div>
              </div>
              <div className="portfolio-result-item highlight">
                <div className="portfolio-result-label">Dollar CVaR</div>
                <div className="portfolio-result-value" style={{ color: '#ef4444', fontSize: 22 }}>
                  {result.dollar_cvar ? formatDollar(result.dollar_cvar) : '—'}
                </div>
              </div>
            </div>

            {result.regime && (
              <div className="portfolio-regime-badge" data-regime={result.regime}>
                Risk Regime: {result.regime}
              </div>
            )}

            {/* Component VaR */}
            {result.component_var && Object.keys(result.component_var).length > 0 && (
              <div className="portfolio-component-var">
                <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Component VaR Breakdown
                </div>
                {Object.entries(result.component_var).map(([ticker, data]) => (
                  <div key={ticker} className="component-var-row">
                    <span className="component-var-ticker">{ticker}</span>
                    <div className="component-var-bar-track">
                      <div
                        className="component-var-bar-fill"
                        style={{ width: `${Math.min(100, Math.abs(data?.contribution_pct || 0))}%` }}
                      />
                    </div>
                    <span className="component-var-value">{(data?.contribution_pct || 0).toFixed(1)}%</span>
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
