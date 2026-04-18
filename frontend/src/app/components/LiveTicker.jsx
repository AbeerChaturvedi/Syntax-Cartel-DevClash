/**
 * LiveTicker — Scrollable asset price ticker strip.
 * Shows real-time prices with color-coded changes.
 */
'use client';

import { memo } from 'react';

function formatPrice(price, assetClass) {
  if (!price) return '—';
  if (assetClass === 'FX') return price.toFixed(4);
  if (assetClass === 'RATE' || assetClass === 'BOND') return price.toFixed(3) + '%';
  if (price > 1000) return price.toLocaleString('en-US', { maximumFractionDigits: 0 });
  return price.toFixed(2);
}

const ASSET_ICONS = {
  EQUITY: '📊',
  FX: '💱',
  BOND: '🏛️',
  RATE: '📉',
  CRYPTO: '₿',
};

function TickerItem({ ticker, data }) {
  const isPositive = (data.pct_change || 0) >= 0;
  const icon = ASSET_ICONS[data.asset_class] || '📊';

  return (
    <div className="ticker-item">
      <span style={{ fontSize: '14px' }}>{icon}</span>
      <span className="ticker-symbol">{ticker}</span>
      <span className="ticker-price">
        {formatPrice(data.price, data.asset_class)}
      </span>
      <span className={`ticker-change ${isPositive ? 'positive' : 'negative'}`}>
        {isPositive ? '▲' : '▼'} {Math.abs(data.pct_change || 0).toFixed(2)}%
      </span>
    </div>
  );
}

const MemoizedTickerItem = memo(TickerItem);

export default function LiveTicker({ assets = {} }) {
  const entries = Object.entries(assets);
  if (entries.length === 0) return null;

  return (
    <div className="ticker-strip">
      {entries.map(([ticker, data]) => (
        <MemoizedTickerItem key={ticker} ticker={ticker} data={data} />
      ))}
    </div>
  );
}
