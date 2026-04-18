/**
 * Project Velure — Main Dashboard Page
 * Real-Time Financial Crisis Early Warning System
 * 
 * Architecture:
 * - WebSocket data → useRef buffer (no re-render)
 * - requestAnimationFrame flush → useState (capped at 60fps)
 * - ECharts canvas rendering for timeline
 * - Canvas rendering for correlation heatmap
 */
'use client';

import { useWebSocket } from '@/lib/useWebSocket';
import CISSGauge from './components/CISSGauge';
import ScoreCards from './components/ScoreCards';
import LiveTicker from './components/LiveTicker';
import AnomalyTimeline from './components/AnomalyTimeline';
import DefaultCards from './components/DefaultCards';
import StressTestButton from './components/StressTestButton';
import AlertBanner from './components/AlertBanner';
import ExplainabilityPanel from './components/ExplainabilityPanel';
import CorrelationHeatmap from './components/CorrelationHeatmap';
import SRISKPanel from './components/SRISKPanel';
import SystemMetrics from './components/SystemMetrics';
import StatusFooter from './components/StatusFooter';
import VaRPanel from './components/VaRPanel';
import ContagionNetwork from './components/ContagionNetwork';

export default function Dashboard() {
  const { isConnected, dashboardData, connectionAttempts } = useWebSocket();

  const data = dashboardData || {};
  const scores = data.scores || {};
  const assets = data.assets || {};
  const merton = data.merton || [];
  const alert = data.alert || null;
  const featureImportance = data.feature_importance || {};
  const cissBreakdown = data.ciss_breakdown || {};
  const correlationMatrix = data.correlation_matrix || [];
  const avgCorrelation = data.avg_correlation || 0;
  const crisisMode = data.crisis_mode || false;
  const tickId = data.tick_id || 0;
  const systemSRISK = data.system_srisk || {};
  const varMetrics = data.var_metrics || {};

  // Loading state
  if (!dashboardData) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
        <div className="loading-text">
          {isConnected ? 'Calibrating ML models...' : 'Connecting to Velure Engine...'}
        </div>
        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          {!isConnected && connectionAttempts > 0 && `Attempt ${connectionAttempts}...`}
        </div>
        <div style={{
          fontSize: '11px', color: 'var(--text-muted)', marginTop: '20px',
          fontFamily: 'var(--font-mono)', textAlign: 'center', lineHeight: '1.8',
        }}>
          Ensure the backend is running:<br />
          <code style={{
            background: 'var(--bg-tertiary)', padding: '4px 8px', borderRadius: '4px',
          }}>
            cd backend && uvicorn main:app --reload
          </code>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-layout">
      {/* ── Header ──────────────────────────────────── */}
      <header className="header">
        <div className="header-left">
          <div className="logo-mark">V</div>
          <div>
            <div className="header-title">Project Velure</div>
            <div className="header-subtitle">Financial Crisis Early Warning System</div>
          </div>
        </div>

        <div className="header-right">
          <div className="tick-counter">
            Tick #{tickId.toLocaleString()}
          </div>

          <StressTestButton crisisMode={crisisMode} />

          <div className={`connection-badge ${isConnected ? 'connected' : 'disconnected'}`}>
            <div className={`pulse-dot ${isConnected ? 'green' : 'red'}`} />
            {isConnected ? 'LIVE' : 'OFFLINE'}
          </div>
        </div>
      </header>

      {/* ── Dashboard Grid ──────────────────────────── */}
      <main className="dashboard-grid">
        {/* Alert Banner (full width) */}
        {alert && <AlertBanner alert={alert} />}

        {/* Row 1: CISS Gauge + Score Cards */}
        <CISSGauge cissScore={scores.ciss || 0} severity={scores.severity} />
        <ScoreCards scores={scores} />

        {/* Row 2: Live Ticker */}
        <LiveTicker assets={assets} />

        {/* Row 3: Anomaly Timeline + Contagion Network */}
        <AnomalyTimeline scores={scores} tickId={tickId} />

        {/* Contagion Network Graph */}
        <div className="card contagion-card">
          <div className="card-header">
            <span className="card-title">Contagion Network</span>
            <span className="card-badge" style={{ background: crisisMode ? 'rgba(239,68,68,0.15)' : 'rgba(99,102,241,0.15)', color: crisisMode ? '#ef4444' : '#6366f1' }}>
              {crisisMode ? 'CONTAGION' : 'STABLE'}
            </span>
          </div>
          <ContagionNetwork
            correlationMatrix={correlationMatrix}
            assets={assets}
            crisisMode={crisisMode}
          />
        </div>

        {/* Sidebar: Default Cards + SRISK + Explainability + Correlation + Metrics */}
        <div className="default-cards-container" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
          {/* Merton Cards */}
          <DefaultCards merton={merton} />

          {/* SRISK Aggregate Panel */}
          <SRISKPanel systemSRISK={systemSRISK} merton={merton} />

          {/* VaR/CVaR Risk Metrics */}
          <div className="card">
            <VaRPanel varMetrics={varMetrics} />
          </div>

          {/* Correlation Heatmap */}
          <div className="card">
            <CorrelationHeatmap 
              matrix={correlationMatrix} 
              avgCorrelation={avgCorrelation} 
            />
          </div>

          {/* Explainability */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Model Explainability</span>
              <span className="card-badge" style={{ background: 'rgba(168,85,247,0.15)', color: '#a855f7' }}>
                XAI
              </span>
            </div>
            <ExplainabilityPanel 
              featureImportance={featureImportance} 
              cissBreakdown={cissBreakdown}
            />
          </div>

          {/* System Health Metrics */}
          <SystemMetrics />
        </div>
      </main>

      {/* ── Status Footer ─────────────────────────── */}
      <StatusFooter tickId={tickId} crisisMode={crisisMode} isConnected={isConnected} />
    </div>
  );
}
