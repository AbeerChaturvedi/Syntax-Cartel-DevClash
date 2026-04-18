/**
 * SystemMetrics — Real-time pipeline health and infrastructure monitoring.
 * Shows ticks/sec, latency, Redis/PostgreSQL status, error rates.
 */
'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function MetricItem({ label, value, unit = '', color = 'var(--text-primary)', mono = true }) {
  return (
    <div className="sys-metric-item">
      <span className="sys-metric-label">{label}</span>
      <span className="sys-metric-value" style={{ color, fontFamily: mono ? 'var(--font-mono)' : 'inherit' }}>
        {value}
        {unit && <span className="sys-metric-unit">{unit}</span>}
      </span>
    </div>
  );
}

function StatusDot({ status }) {
  const color = status === 'connected' || status === 'redis-streams'
    ? '#22c55e'
    : status === 'fallback' || status === 'in-process'
    ? '#eab308'
    : '#ef4444';

  return (
    <span className="sys-status-dot" style={{ background: color, boxShadow: `0 0 6px ${color}60` }} />
  );
}

export default function SystemMetrics() {
  const [metrics, setMetrics] = useState(null);

  const fetchMetrics = useCallback(async () => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const res = await fetch(`${API_URL}/api/metrics`, { signal: controller.signal });
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
    } catch {
      // Silent fail — metrics are non-critical
    } finally {
      clearTimeout(timeout);
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 3000);
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  if (!metrics) return null;

  const redis = metrics.redis || {};
  const stream = metrics.stream || {};

  const formatUptime = (s) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = Math.floor(s % 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m ${sec}s`;
  };

  return (
    <div className="card sys-metrics-panel">
      <div className="card-header">
        <span className="card-title">Pipeline Health</span>
        <span className="card-badge" style={{
          background: metrics.pipeline_errors === 0 ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
          color: metrics.pipeline_errors === 0 ? '#22c55e' : '#ef4444',
        }}>
          {metrics.pipeline_errors === 0 ? 'NOMINAL' : `${metrics.pipeline_errors} ERR`}
        </span>
      </div>

      <div className="sys-metrics-grid">
        {/* Throughput */}
        <MetricItem
          label="Throughput"
          value={metrics.ticks_per_second?.toFixed(1)}
          unit="tps"
          color="var(--accent)"
        />
        <MetricItem
          label="Latency"
          value={metrics.avg_pipeline_latency_ms?.toFixed(1)}
          unit="ms"
          color={metrics.avg_pipeline_latency_ms > 100 ? 'var(--orange)' : 'var(--green)'}
        />
        <MetricItem
          label="Uptime"
          value={formatUptime(metrics.uptime_seconds || 0)}
          color="var(--text-secondary)"
          mono={false}
        />
        <MetricItem
          label="Clients"
          value={metrics.connected_clients || 0}
          color="var(--blue)"
        />
      </div>

      {/* Infrastructure Status */}
      <div className="sys-infra-section">
        <div className="sys-infra-item">
          <StatusDot status={redis.redis_connected ? 'connected' : redis.fallback_mode ? 'fallback' : 'offline'} />
          <span className="sys-infra-label">Redis</span>
          <span className="sys-infra-status">
            {redis.redis_connected ? 'Streams' : redis.fallback_mode ? 'In-Process' : 'Offline'}
          </span>
        </div>
        <div className="sys-infra-item">
          <StatusDot status={metrics.db_writes > 0 || metrics.db_errors === 0 ? 'connected' : 'offline'} />
          <span className="sys-infra-label">PostgreSQL</span>
          <span className="sys-infra-status">
            {metrics.db_writes > 0 ? `${metrics.db_writes} writes` : metrics.db_errors > 0 ? 'Error' : 'Standby'}
          </span>
        </div>
      </div>

      {/* Peak Scores */}
      <div className="sys-peaks-row">
        <div className="sys-peak-item">
          <span className="sys-peak-label">Peak CISS</span>
          <span className="sys-peak-value" style={{
            color: metrics.peak_ciss > 0.7 ? '#ef4444' : metrics.peak_ciss > 0.3 ? '#eab308' : '#22c55e'
          }}>
            {(metrics.peak_ciss * 100).toFixed(1)}%
          </span>
        </div>
        <div className="sys-peak-item">
          <span className="sys-peak-label">Crisis Events</span>
          <span className="sys-peak-value" style={{
            color: metrics.crisis_events > 0 ? '#ef4444' : 'var(--text-secondary)'
          }}>
            {metrics.crisis_events}
          </span>
        </div>
        <div className="sys-peak-item">
          <span className="sys-peak-label">Backlog</span>
          <span className="sys-peak-value" style={{
            color: (redis.backlog || 0) > 100 ? '#f97316' : 'var(--text-secondary)'
          }}>
            {redis.backlog || 0}
          </span>
        </div>
      </div>
    </div>
  );
}
