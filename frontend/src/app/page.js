/**
 * Project Velure — Main Dashboard Page (v3)
 * Real-Time Financial Crisis Early Warning System
 * 
 * Architecture:
 * - WebSocket data → useRef buffer (no re-render)
 * - requestAnimationFrame flush → useState (capped at 60fps)
 * - ECharts canvas rendering for timeline
 * - Canvas rendering for correlation heatmap + ROC curves
 * - All 19 components wired to live data
 */
'use client';

import { useWebSocket } from '@/lib/useWebSocket';
import CISSGauge from './components/CISSGauge';
import ScoreCards from './components/ScoreCards';
import LiveTicker from './components/LiveTicker';
import AnomalyTimeline from './components/AnomalyTimeline';
import DefaultCards from './components/DefaultCards';
import StressTestButton from './components/StressTestButton';
import SpeedControl from './components/SpeedControl';
import AlertBanner from './components/AlertBanner';
import ExplainabilityPanel from './components/ExplainabilityPanel';
import CorrelationHeatmap from './components/CorrelationHeatmap';
import SRISKPanel from './components/SRISKPanel';
import SystemMetrics from './components/SystemMetrics';
import StatusFooter from './components/StatusFooter';
import VaRPanel from './components/VaRPanel';
import ContagionNetwork from './components/ContagionNetwork';
import TailDependenceMatrix from './components/TailDependenceMatrix';
import PortfolioBuilder from './components/PortfolioBuilder';
import BacktestView from './components/BacktestView';
import ReplayController from './components/ReplayController';

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
  const copula = data.copula || null;

  // Loading state
  if (!dashboardData) {
    return (
      <div className="loading-container">
        <div className="loading-logo">
          <div className="loading-logo-mark">V</div>
          <div className="loading-logo-ring" />
        </div>
        <div className="loading-text">
          {isConnected ? 'Calibrating ML models...' : 'Connecting to Velure Engine...'}
        </div>
        <div className="loading-sub">
          {!isConnected && connectionAttempts > 0 && `Attempt ${connectionAttempts}...`}
        </div>
        <div className="loading-models">
          <div className="loading-model-item">
            <span className="loading-model-dot" style={{ animationDelay: '0s' }} />
            Isolation Forest (200 trees)
          </div>
          <div className="loading-model-item">
            <span className="loading-model-dot" style={{ animationDelay: '0.2s' }} />
            LSTM Autoencoder (72→32→72)
          </div>
          <div className="loading-model-item">
            <span className="loading-model-dot" style={{ animationDelay: '0.4s' }} />
            CISS Scorer (5 segments)
          </div>
          <div className="loading-model-item">
            <span className="loading-model-dot" style={{ animationDelay: '0.6s' }} />
            t-Copula + GARCH(1,1)
          </div>
          <div className="loading-model-item">
            <span className="loading-model-dot" style={{ animationDelay: '0.8s' }} />
            Merton DD + SRISK
          </div>
        </div>
        <div className="loading-hint">
          Ensure the backend is running:<br />
          <code className="loading-code">
            docker compose up --build
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
          <SpeedControl />

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
            <span
              className="card-badge"
              style={{
                color: crisisMode ? 'var(--red)' : 'var(--text-tertiary)',
                borderColor: crisisMode ? 'var(--red)' : 'var(--border-active)',
              }}
            >
              {crisisMode ? 'CONTAGION' : 'STABLE'}
            </span>
          </div>
          <ContagionNetwork
            correlationMatrix={correlationMatrix}
            assets={assets}
            crisisMode={crisisMode}
          />
        </div>

        {/* Sidebar: Default Cards + SRISK + Tail + VaR + Corr + Explain + Metrics */}
        <div className="default-cards-container" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-md)' }}>
          {/* Merton Cards */}
          <DefaultCards merton={merton} />

          {/* SRISK Aggregate Panel */}
          <SRISKPanel systemSRISK={systemSRISK} merton={merton} />

          {/* Tail Dependence Matrix (t-Copula) */}
          <div className="card">
            <TailDependenceMatrix copula={copula} />
          </div>

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
              <span className="card-badge">XAI</span>
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

      {/* ── v3 Panels (full-width below main grid) ────────── */}
      <section className="v3-panels">
        <PortfolioBuilder />
        <div className="v3-panels-row">
          <ReplayController />
          <BacktestView />
        </div>
      </section>

      {/* ── Status Footer ─────────────────────────── */}
      <StatusFooter tickId={tickId} crisisMode={crisisMode} isConnected={isConnected} />
    </div>
  );
}
