'use client';
/**
 * ErrorBoundary — wraps WS-dependent UI so a single component crash
 * doesn't take the whole dashboard down (issue 4.3 from FIXES_REQUIRED.md).
 */
import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // Surface to the console; production would post to /api/audit
    console.error('Velure ErrorBoundary caught:', error, info?.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: '12px 16px',
          color: '#ef4444',
          fontSize: '12px',
          fontFamily: 'var(--font-mono, monospace)',
          background: 'var(--bg-primary, #0f172a)',
          border: '1px solid #ef444433',
          borderRadius: '6px',
        }}>
          <strong>Component error:</strong>{' '}
          {String(this.state.error?.message ?? this.state.error ?? 'unknown')}
        </div>
      );
    }
    return this.props.children;
  }
}