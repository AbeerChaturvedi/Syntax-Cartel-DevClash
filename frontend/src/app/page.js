/**
 * Project Velure — Main Dashboard (v6 — Institutional)
 * Professional three-column layout for institutional investors.
 * Clean transitions, no playful animations.
 */
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWebSocket } from '@/lib/useWebSocket';
import {
  Sun, Moon, BarChart3, Shield, Activity, Zap, Radio,
  ChevronRight, Clock, Wifi, WifiOff
} from 'lucide-react';

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
import MarketNews from './components/MarketNews';

/* ── Agent definitions ──────────────────────────────── */
const AGENTS = [
  {
    id: 'model-outputs',
    label: 'Model Outputs',
    icon: BarChart3,
    description: 'Ensemble anomaly scores',
  },
  {
    id: 'distance-to-default',
    label: 'Distance to Default',
    icon: Shield,
    description: 'Merton structural credit risk',
  },
  {
    id: 'anomaly-detection',
    label: 'Anomaly Detection',
    icon: Activity,
    description: 'Anomaly score timeline',
  },
  {
    id: 'risk-metrics',
    label: 'Risk Metrics',
    icon: Zap,
    description: 'VaR, CVaR, SRISK',
  },
  {
    id: 'market-intel',
    label: 'Market Intel',
    icon: Radio,
    description: 'News, portfolio, replay',
  },
];

/* ── Theme Toggle Hook ───────────────────────────────── */
function useTheme() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem('velure-theme');
    if (stored === 'dark') {
      setDark(true);
      document.documentElement.classList.add('dark');
    } else {
      setDark(false);
      document.documentElement.classList.remove('dark');
    }
  }, []);

  const toggle = useCallback(() => {
    setDark((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add('dark');
        localStorage.setItem('velure-theme', 'dark');
      } else {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('velure-theme', 'light');
      }
      return next;
    });
  }, []);

  return { dark, toggle };
}

/* ── Live Clock ──────────────────────────────────────── */
function useClock() {
  const [time, setTime] = useState('');
  useEffect(() => {
    const tick = () => {
      setTime(
        new Date().toLocaleTimeString('en-US', {
          hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        })
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return time;
}

/* ── Activity Feed ───────────────────────────────────── */
function useActivityFeed(dashboardData, isConnected) {
  const [activities, setActivities] = useState([]);
  const prevSeverity = useRef(null);
  const prevCrisisMode = useRef(null);
  const tickMilestone = useRef(0);

  useEffect(() => {
    if (!dashboardData) return;
    const now = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
    const newItems = [];

    const severity = dashboardData.scores?.severity;
    if (severity && severity !== prevSeverity.current && prevSeverity.current !== null) {
      newItems.push({
        id: Date.now() + '-sev',
        text: `Severity level: ${severity}`,
        time: now,
        type: severity === 'NORMAL' ? 'info' : (severity === 'CRITICAL' || severity === 'SEVERE') ? 'danger' : 'warn',
      });
    }
    prevSeverity.current = severity;

    const crisisMode = dashboardData.crisis_mode;
    if (crisisMode !== prevCrisisMode.current && prevCrisisMode.current !== null) {
      newItems.push({
        id: Date.now() + '-crisis',
        text: crisisMode ? 'Stress test initiated' : 'Normal operations resumed',
        time: now,
        type: crisisMode ? 'danger' : 'info',
      });
    }
    prevCrisisMode.current = crisisMode;

    const tickId = dashboardData.tick_id || 0;
    const milestone = Math.floor(tickId / 100) * 100;
    if (milestone > tickMilestone.current && tickMilestone.current > 0) {
      newItems.push({
        id: Date.now() + '-tick',
        text: `Tick ${milestone.toLocaleString()}`,
        time: now,
        type: 'info',
      });
    }
    tickMilestone.current = milestone;

    if (dashboardData.alert) {
      const existing = activities.find(a => a.text?.includes(dashboardData.alert.message?.slice(0, 30)));
      if (!existing) {
        newItems.push({
          id: Date.now() + '-alert',
          text: dashboardData.alert.message || 'Alert triggered',
          time: now,
          type: 'danger',
        });
      }
    }

    if (newItems.length > 0) {
      setActivities(prev => [...newItems, ...prev].slice(0, 10));
    }
  }, [dashboardData]);

  useEffect(() => {
    const now = new Date().toLocaleTimeString('en-US', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    });
    if (isConnected) {
      setActivities(prev => [{
        id: Date.now() + '-conn',
        text: 'WebSocket connected',
        time: now,
        type: 'info',
      }, ...prev].slice(0, 10));
    }
  }, [isConnected]);

  return activities;
}

/* ── Type color mapping ──────────────────────────────── */
const typeColors = {
  info: 'var(--text-muted)',
  warn: 'var(--yellow)',
  danger: 'var(--red)',
};

/* ── Main Dashboard ──────────────────────────────────── */
export default function Dashboard() {
  const { isConnected, dashboardData, connectionAttempts } = useWebSocket();
  const { dark, toggle: toggleTheme } = useTheme();
  const [activeAgent, setActiveAgent] = useState('model-outputs');
  const time = useClock();

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

  const activities = useActivityFeed(dashboardData, isConnected);

  /* ── Loading ───────────────────────────────────── */
  if (!dashboardData) {
    return (
      <div className="loading-container">
        <div className="loading-logo">
          <div className="loading-logo-mark">V</div>
          <div className="loading-logo-ring" />
        </div>
        <div className="loading-text">
          {isConnected ? 'Initializing models...' : 'Connecting to engine...'}
        </div>
        <div className="loading-sub">
          {!isConnected && connectionAttempts > 0 && `Attempt ${connectionAttempts}`}
        </div>
        <div className="loading-models">
          {[
            'Isolation Forest',
            'LSTM Autoencoder',
            'CISS Scorer',
            't-Copula + GARCH',
            'Merton DD + SRISK',
          ].map((model, i) => (
            <div key={model} className="loading-model-item">
              <span className="loading-model-dot" style={{ animationDelay: `${i * 0.2}s` }} />
              {model}
            </div>
          ))}
        </div>
        <div className="loading-hint">
          Backend: <code className="loading-code">docker compose up --build</code>
        </div>
      </div>
    );
  }

  /* ── Agent content ─────────────────────────────── */
  const renderAgentContent = () => {
    const agentMeta = AGENTS.find(a => a.id === activeAgent);

    const content = (() => {
      switch (activeAgent) {
        case 'model-outputs':
          return (
            <>
              {alert && <AlertBanner alert={alert} />}
              <LiveTicker assets={assets} />
              <ScoreCards scores={scores} />
              <div style={{ marginTop: 16 }}>
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
              </div>
            </>
          );

        case 'distance-to-default':
          return (
            <>
              {alert && <AlertBanner alert={alert} />}
              <DefaultCards merton={merton} />
              <div style={{ marginTop: 16 }}>
                <SRISKPanel systemSRISK={systemSRISK} merton={merton} />
              </div>
            </>
          );

        case 'anomaly-detection':
          return (
            <>
              {alert && <AlertBanner alert={alert} />}
              <AnomalyTimeline scores={scores} tickId={tickId} />
              <div style={{ marginTop: 16 }}>
                <div className="card">
                  <CorrelationHeatmap
                    matrix={correlationMatrix}
                    avgCorrelation={avgCorrelation}
                  />
                </div>
              </div>
            </>
          );

        case 'risk-metrics':
          return (
            <>
              {alert && <AlertBanner alert={alert} />}
              <div className="card" style={{ marginBottom: 16 }}>
                <VaRPanel varMetrics={varMetrics} />
              </div>
              <div className="card" style={{ marginBottom: 16 }}>
                <TailDependenceMatrix copula={copula} />
              </div>
              <SystemMetrics />
            </>
          );

        case 'market-intel':
          return (
            <>
              <MarketNews />
              <div style={{ marginTop: 16 }}>
                <PortfolioBuilder />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
                <ReplayController />
                <BacktestView />
              </div>
            </>
          );

        default:
          return null;
      }
    })();

    return (
      <>
        <div className="main-content-header">
          <h1 className="main-content-title">{agentMeta?.label}</h1>
          <p className="main-content-subtitle">{agentMeta?.description}</p>
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={activeAgent}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
          >
            {content}
          </motion.div>
        </AnimatePresence>
      </>
    );
  };

  return (
    <div className="app-shell">
      <div className="app-container">
        {/* Header */}
        <header className="header">
          <div className="header-left">
            <div className="logo-mark">V</div>
            <div>
              <div className="header-title">Velure</div>
              <div className="header-subtitle">Financial Crisis Early Warning System</div>
            </div>
          </div>

          <div className="header-right">
            <SpeedControl />

            <div className="tick-counter">
              <Clock size={11} style={{ opacity: 0.4 }} />
              {time}
            </div>

            <div className="tick-counter">
              T{tickId.toLocaleString()}
            </div>

            <button
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label="Toggle theme"
            >
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>

            <div className={`connection-badge ${isConnected ? 'connected' : 'disconnected'}`}>
              <div className={`pulse-dot ${isConnected ? 'green' : 'red'}`} />
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </div>
          </div>
        </header>

        {/* Left Sidebar */}
        <aside className="left-sidebar">
          <div className="sidebar-crisis-section">
            <div className="sidebar-section-title">Stress Test</div>
            <StressTestButton crisisMode={crisisMode} />
          </div>

          <div className="sidebar-section">
            <div className="sidebar-section-title">Views</div>
            {AGENTS.map((agent) => {
              const Icon = agent.icon;
              const isActive = activeAgent === agent.id;
              return (
                <button
                  key={agent.id}
                  className={`sidebar-nav-item ${isActive ? 'active' : ''}`}
                  onClick={() => setActiveAgent(agent.id)}
                >
                  <Icon className="sidebar-nav-icon" size={16} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span>{agent.label}</span>
                    {isActive && (
                      <div className="sidebar-nav-desc">{agent.description}</div>
                    )}
                  </div>
                  {isActive && (
                    <ChevronRight size={12} style={{ opacity: 0.3, flexShrink: 0 }} />
                  )}
                </button>
              );
            })}
          </div>

          <div style={{ marginTop: 'auto', padding: '16px 28px' }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 10, color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
            }}>
              {isConnected
                ? <Wifi size={12} style={{ color: 'var(--green)' }} />
                : <WifiOff size={12} style={{ color: 'var(--red)' }} />
              }
              {isConnected ? 'Engine connected' : 'Reconnecting...'}
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="main-content">
          {renderAgentContent()}
        </main>

        {/* Right Sidebar */}
        <aside className="right-sidebar">
          <div className="widget-card">
            <div className="widget-card-title">
              <span>Contagion Network</span>
              <span
                className="card-badge"
                style={{
                  color: crisisMode ? 'var(--red)' : 'var(--text-muted)',
                  borderColor: crisisMode ? 'var(--red)' : 'var(--border-primary)',
                }}
              >
                {crisisMode ? 'STRESS' : 'NORMAL'}
              </span>
            </div>
            <ContagionNetwork
              correlationMatrix={correlationMatrix}
              assets={assets}
              crisisMode={crisisMode}
            />
          </div>

          <CISSGauge cissScore={scores.ciss || 0} severity={scores.severity} />

          <div className="widget-card">
            <div className="widget-card-title">
              <span>Event Log</span>
              {activities.length > 0 && (
                <span style={{
                  fontSize: 9, fontWeight: 600, color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}>
                  {activities.length}
                </span>
              )}
            </div>
            <div className="activity-feed">
              {activities.length === 0 ? (
                <div className="activity-empty">
                  Awaiting events
                </div>
              ) : (
                activities.map((item) => (
                  <div key={item.id} className="activity-item">
                    <div
                      className="activity-dot"
                      style={{ background: typeColors[item.type] || 'var(--text-muted)' }}
                    />
                    <div>
                      <div className="activity-text">{item.text}</div>
                      <div className="activity-time">{item.time}</div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>
      </div>

      <StatusFooter tickId={tickId} crisisMode={crisisMode} isConnected={isConnected} />
    </div>
  );
}
