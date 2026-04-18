'use client';

import { useRef, useEffect, memo } from 'react';

/**
 * ContagionNetwork — Canvas-rendered force-directed network graph
 * showing cross-asset correlation strength as connections.
 * 
 * During crisis mode, edges thicken and turn red as correlations spike,
 * visually demonstrating contagion propagation.
 */
const ContagionNetwork = memo(function ContagionNetwork({ correlationMatrix, assets, crisisMode }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const nodesRef = useRef([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;

    const resize = () => {
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = rect.width + 'px';
      canvas.style.height = rect.height + 'px';
      ctx.scale(dpr, dpr);
    };
    resize();

    const tickers = Object.keys(assets || {});
    if (tickers.length === 0) return;

    // Asset class colors
    const classColors = {
      EQUITY: '#6366f1',
      FX: '#22d3ee',
      CRYPTO: '#f59e0b',
      BOND: '#10b981',
      RATE: '#8b5cf6',
    };

    const W = canvas.width / dpr;
    const H = canvas.height / dpr;
    const cx = W / 2;
    const cy = H / 2;
    const radius = Math.min(W, H) * 0.36;

    // Initialize node positions in a circle
    if (nodesRef.current.length !== tickers.length) {
      nodesRef.current = tickers.map((ticker, i) => {
        const angle = (2 * Math.PI * i) / tickers.length - Math.PI / 2;
        const assetClass = (assets[ticker]?.asset_class || 'EQUITY').toUpperCase();
        return {
          ticker,
          x: cx + radius * Math.cos(angle),
          y: cy + radius * Math.sin(angle),
          tx: cx + radius * Math.cos(angle),
          ty: cy + radius * Math.sin(angle),
          color: classColors[assetClass] || '#6366f1',
          assetClass,
          pctChange: 0,
        };
      });
    }

    // Update node data
    nodesRef.current.forEach((node) => {
      const d = assets[node.ticker];
      if (d) {
        node.pctChange = d.pct_change || 0;
      }
    });

    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      const nodes = nodesRef.current;
      const matrix = correlationMatrix || [];

      // Smooth position interpolation
      nodes.forEach(n => {
        n.x += (n.tx - n.x) * 0.05;
        n.y += (n.ty - n.y) * 0.05;
      });

      // Draw edges (correlations)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          let corr = 0;
          if (matrix[i] && matrix[i][j] !== undefined) {
            corr = Math.abs(matrix[i][j]);
          }

          if (corr < 0.15) continue; // skip weak correlations

          const strength = Math.min(corr, 1);
          const lineWidth = 0.5 + strength * 3;

          // Color: blue for normal, red for high correlation (contagion)
          let r, g, b;
          if (strength > 0.6) {
            // High correlation → red/orange (contagion)
            r = 239; g = 68; b = 68;
          } else if (strength > 0.35) {
            // Medium → yellow
            r = 234; g = 179; b = 8;
          } else {
            // Low → dim blue
            r = 99; g = 102; b = 241;
          }

          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.strokeStyle = `rgba(${r},${g},${b},${0.1 + strength * 0.5})`;
          ctx.lineWidth = lineWidth;
          ctx.stroke();
        }
      }

      // Draw nodes
      nodes.forEach((node) => {
        const isNegative = node.pctChange < -0.001;
        const nodeRadius = isNegative && crisisMode ? 8 : 5;

        // Glow for crisis
        if (crisisMode && isNegative) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius + 4, 0, 2 * Math.PI);
          ctx.fillStyle = 'rgba(239, 68, 68, 0.15)';
          ctx.fill();
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, nodeRadius, 0, 2 * Math.PI);
        ctx.fillStyle = isNegative ? '#ef4444' : node.color;
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.3)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Label
        ctx.font = '9px Inter, sans-serif';
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.textAlign = 'center';
        ctx.fillText(node.ticker, node.x, node.y - nodeRadius - 4);
      });

      // Title legend (bottom-left)
      ctx.font = '9px Inter, sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.3)';
      ctx.textAlign = 'left';
      let ly = H - 8;
      const legend = [
        { color: '#6366f1', label: 'Equity' },
        { color: '#22d3ee', label: 'FX' },
        { color: '#f59e0b', label: 'Crypto' },
        { color: '#10b981', label: 'Bond' },
      ];
      legend.forEach((item, idx) => {
        const lx = 8 + idx * 58;
        ctx.fillStyle = item.color;
        ctx.fillRect(lx, ly - 6, 6, 6);
        ctx.fillStyle = 'rgba(255,255,255,0.4)';
        ctx.fillText(item.label, lx + 10, ly);
      });

      animRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [correlationMatrix, assets, crisisMode]);

  return (
    <div className="contagion-network">
      <canvas
        ref={canvasRef}
        style={{ width: '100%', height: '100%', display: 'block' }}
      />
    </div>
  );
});

export default ContagionNetwork;
