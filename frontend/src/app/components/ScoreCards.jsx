/**
 * ScoreCards — Institutional model-output panel.
 * Hero card shows the 1-min display_score (stable enough to act on).
 * Component cards show smoothed model contributions, no flashing colors.
 */
'use client';

function getStateColor(score) {
  if (score < 0.30) return 'var(--green)';
  if (score < 0.50) return 'var(--yellow)';
  if (score < 0.70) return 'var(--orange)';
  return 'var(--red)';
}

function ScoreCard({ label, value, hero = false }) {
  const color = getStateColor(value);
  const pct = Math.min(100, value * 100);
  return (
    <div className={`score-card${hero ? ' hero' : ''}`}>
      <div className="score-card-label">{label}</div>
      <div className="score-card-value" style={{ color }}>
        {(value * 100).toFixed(hero ? 2 : 1)}
        <span className="score-card-pct">%</span>
      </div>
      <div className="score-card-bar">
        <div
          className="score-card-bar-fill"
          style={{
            background: color,
            width: `${pct}%`,
            transition: 'width 1.4s ease-out, background 1.4s ease-out',
          }}
        />
      </div>
    </div>
  );
}

export default function ScoreCards({ scores = {} }) {
  const ifScore   = scores.isolation_forest  || 0;
  const lstmScore = scores.lstm_autoencoder  || 0;
  // Hero = 1-min median display_score; instantaneous combined is the ghost.
  const display   = scores.display_score ?? scores.combined_anomaly ?? 0;
  const ghost     = scores.combined_anomaly  || 0;
  const ciss      = scores.ciss              || 0;
  const copula    = scores.copula_tail       || 0;
  const severity  = scores.severity || 'NORMAL';

  return (
    <div className="card score-cards-container">
      <div className="card-header">
        <span className="card-title">Model Outputs · 1-min display</span>
        <span className="card-badge" style={{ color: getStateColor(display), borderColor: getStateColor(display) }}>
          {severity}
        </span>
      </div>
      <div className="score-cards-grid">
        <ScoreCard label="Crisis Score (1-min)" value={display} hero />
        <ScoreCard label="Isolation Forest" value={ifScore} />
        <ScoreCard label="LSTM Autoencoder" value={lstmScore} />
        <ScoreCard label="CISS Stress" value={ciss} />
        <ScoreCard label="t-Copula Tail" value={copula} />
      </div>
      <div className="score-card-ghost">
        Instantaneous: <span style={{ color: getStateColor(ghost) }}>{(ghost * 100).toFixed(2)}%</span>
      </div>
    </div>
  );
}
