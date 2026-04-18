'use client';

import { useState, useEffect } from 'react';

export default function MarketNews() {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;

    const fetchNews = async () => {
      try {
        setLoading(true);
        // Proxy through backend to avoid exposing API keys
        const res = await fetch('http://localhost:8000/api/news');
        if (!res.ok) {
          throw new Error('Network response was not ok');
        }
        
        const data = await res.json();
        
        if (data.status === 'ok' && active) {
          setArticles(data.articles || []);
          setError(null);
        } else if (active) {
          setError(data.message || 'Failed to fetch news');
        }
      } catch (err) {
        if (active) {
          setError(err.message || 'An error occurred fetching news');
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    // Initial fetch
    fetchNews();

    // Poll every 60 seconds
    const intervalId = setInterval(fetchNews, 60000);

    return () => {
      active = false;
      clearInterval(intervalId);
    };
  }, []);

  return (
    <div className="card market-news-card" style={{ display: 'flex', flexDirection: 'column', height: '350px', flex: '0 0 auto' }}>
      <div className="card-header" style={{ marginBottom: '0.75rem', paddingBottom: '0.5rem', borderBottom: '1px solid var(--border-subtle)' }}>
        <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"></path>
            <path d="M18 14h-8"></path>
            <path d="M15 18h-5"></path>
            <path d="M10 6h8v4h-8V6Z"></path>
          </svg>
          Live Market Intel
        </span>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span style={{ fontSize: '0.65rem', color: 'var(--text-tertiary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {loading ? 'SYNCING...' : 'LIVE'}
          </span>
          <div className={`pulse-dot ${loading ? 'yellow' : error ? 'red' : 'green'}`} />
        </div>
      </div>

      <div className="market-news-content" style={{ display: 'flex', flexDirection: 'column', gap: '0.85rem', overflowY: 'auto', paddingRight: '4px', flexGrow: 1 }}>
        {loading && articles.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontSize: '0.875rem', padding: '1rem', textAlign: 'center' }}>Aggregating global headlines...</div>
        ) : error && articles.length === 0 ? (
          <div style={{ color: 'var(--red)', fontSize: '0.875rem', padding: '1rem', textAlign: 'center', background: 'rgba(255,0,0,0.05)', borderRadius: '4px' }}>
            Data Feed Offline: {error === 'NEWSDATA_API_KEY not configured' ? 'System running in local fallback.' : error}
          </div>
        ) : articles.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontSize: '0.875rem', padding: '1rem', textAlign: 'center' }}>No intel anomalies detected.</div>
        ) : (
          articles.map((article, index) => (
            <a
              key={index}
              href={article.link}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'block',
                textDecoration: 'none',
                color: 'inherit',
                borderLeft: '2px solid transparent',
                paddingLeft: '0.5rem',
                transition: 'all 0.2s ease',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderLeftColor = 'var(--accent)';
                e.currentTarget.style.backgroundColor = 'var(--bg-elevated)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderLeftColor = 'transparent';
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <div style={{ fontSize: '0.8rem', fontWeight: 500, lineHeight: 1.3, color: 'var(--text-primary)', marginBottom: '0.35rem' }}>
                {article.title}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.65rem', color: 'var(--text-tertiary)' }}>
                <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{article.source}</span>
                <span>
                  {article.pubDate ? new Date(article.pubDate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : 'Just now'}
                </span>
              </div>
            </a>
          ))
        )}
      </div>
    </div>
  );
}
