/**
 * AnomalyTimeline — Real-time anomaly score timeline using ECharts.
 * Canvas-rendered for 60fps with thousands of data points.
 */
'use client';

import { useRef, useEffect, useMemo, useCallback } from 'react';
import * as echarts from 'echarts';

const MAX_POINTS = 200;

export default function AnomalyTimeline({ scores = {}, tickId = 0 }) {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);
  const dataRef = useRef({
    timestamps: [],
    ifScores: [],
    lstmScores: [],
    combined: [],
    ciss: [],
  });

  // Initialize chart
  useEffect(() => {
    if (!chartRef.current) return;

    chartInstance.current = echarts.init(chartRef.current, null, {
      renderer: 'canvas',
    });

    const option = {
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        top: 40,
        right: 20,
        bottom: 30,
        left: 50,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(15, 15, 16, 0.97)',
        borderColor: '#2a2a2e',
        borderWidth: 1,
        textStyle: {
          color: '#e8e6e3',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11,
        },
        axisPointer: {
          type: 'cross',
          lineStyle: { color: 'rgba(255, 140, 0, 0.5)' },
          crossStyle: { color: 'rgba(255, 140, 0, 0.5)' },
        },
      },
      legend: {
        data: ['Isolation Forest', 'LSTM Autoencoder', 'Combined', 'CISS'],
        top: 5,
        textStyle: {
          color: '#94a3b8',
          fontFamily: "'Inter', sans-serif",
          fontSize: 11,
        },
        itemWidth: 16,
        itemHeight: 2,
      },
      xAxis: {
        type: 'category',
        data: [],
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
        axisLabel: { color: '#64748b', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLine: { show: false },
        axisLabel: {
          color: '#64748b',
          fontSize: 10,
          fontFamily: "'JetBrains Mono', monospace",
          formatter: (v) => (v * 100).toFixed(0) + '%',
        },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      },
      series: [
        {
          name: 'Isolation Forest',
          type: 'line',
          smooth: false,
          symbol: 'none',
          lineStyle: { width: 1.2, color: '#5b8db8' },
          data: [],
        },
        {
          name: 'LSTM Autoencoder',
          type: 'line',
          smooth: false,
          symbol: 'none',
          lineStyle: { width: 1.2, color: '#a8a59f' },
          data: [],
        },
        {
          name: 'Combined',
          type: 'line',
          smooth: false,
          symbol: 'none',
          lineStyle: { width: 1.8, color: '#ff8c00' },
          data: [],
        },
        {
          name: 'CISS',
          type: 'line',
          smooth: false,
          symbol: 'none',
          lineStyle: { width: 1.2, color: '#c9a227', type: 'dashed' },
          data: [],
        },
      ],
      // Threshold line
      markLine: {
        silent: true,
        data: [
          {
            yAxis: 0.7,
            lineStyle: { color: '#ef4444', width: 1, type: 'dashed' },
            label: { show: true, formatter: 'Alert Threshold', color: '#ef4444', fontSize: 10 },
          },
        ],
      },
    };

    // Add threshold markLine to combined series
    option.series[2].markLine = {
      silent: true,
      symbol: 'none',
      data: [
        {
          yAxis: 0.7,
          lineStyle: { color: 'rgba(239, 68, 68, 0.4)', width: 1, type: 'dashed' },
          label: {
            show: true,
            position: 'insideEndTop',
            formatter: 'ALERT',
            color: '#ef4444',
            fontSize: 9,
            fontFamily: "'JetBrains Mono', monospace",
          },
        },
      ],
    };

    chartInstance.current.setOption(option);

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
    };
  }, []);

  // Update data
  useEffect(() => {
    if (!chartInstance.current || !tickId) return;

    const d = dataRef.current;
    const now = new Date().toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });

    d.timestamps.push(now);
    d.ifScores.push(scores.isolation_forest || 0);
    d.lstmScores.push(scores.lstm_autoencoder || 0);
    d.combined.push(scores.combined_anomaly || 0);
    d.ciss.push(scores.ciss || 0);

    // Trim to max points
    if (d.timestamps.length > MAX_POINTS) {
      d.timestamps.shift();
      d.ifScores.shift();
      d.lstmScores.shift();
      d.combined.shift();
      d.ciss.shift();
    }

    chartInstance.current.setOption({
      xAxis: { data: d.timestamps },
      series: [
        { data: d.ifScores },
        { data: d.lstmScores },
        { data: d.combined },
        { data: d.ciss },
      ],
    });
  }, [tickId, scores]);

  return (
    <div className="card anomaly-chart-container">
      <div className="card-header">
        <span className="card-title">Anomaly Detection Timeline</span>
        <span className="card-badge">LIVE</span>
      </div>
      <div ref={chartRef} className="chart-container" />
    </div>
  );
}
