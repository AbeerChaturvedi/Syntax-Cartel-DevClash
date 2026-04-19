import time
import json
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter
from utils.config import NEWSDATA_API_KEY
from utils.logger import api_log
from globals import _news_cache

router = APIRouter()

@router.get("/api/news")
async def get_market_news():
    """Proxy endpoint to fetch top business/financial news."""
    now = time.time()
    # Cache for 5 minutes (300 seconds)
    if _news_cache["data"] and (now - _news_cache["timestamp"] < 300):
        return {"status": "ok", "cached": True, "articles": _news_cache["data"]}

    if not NEWSDATA_API_KEY:
        # Fallback to realistic mock data for hackathon demonstrations
        mock_articles = [
            {"title": "Global Markets Rally as Inflation Data Cools Ahead of Fed Meeting", "link": "https://www.ft.com/markets", "source": "Financial Times", "pubDate": datetime.now(timezone.utc).isoformat()},
            {"title": "Tech Sector Leads S&P 500 Higher Amid AI Chip Demand Splurge", "link": "https://www.bloomberg.com/markets", "source": "Bloomberg", "pubDate": datetime.now(timezone.utc).isoformat()},
            {"title": "European Central Bank Signals Potential Rate Cut in Upcoming Quarter", "link": "https://www.reuters.com/markets", "source": "Reuters", "pubDate": datetime.now(timezone.utc).isoformat()},
            {"title": "Oil Prices Stabilize Following OPEC+ Supply Adjustments", "link": "https://www.wsj.com/finance", "source": "Wall Street Journal", "pubDate": datetime.now(timezone.utc).isoformat()},
            {"title": "Treasury Yields Dip as Investors Weigh Recession Risks", "link": "https://www.cnbc.com/markets/", "source": "CNBC", "pubDate": datetime.now(timezone.utc).isoformat()},
            {"title": "Banking Sector Stress Tests Reveal Strong Capital Buffers", "link": "https://www.bloomberg.com/markets", "source": "Bloomberg", "pubDate": datetime.now(timezone.utc).isoformat()}
        ]
        return {"status": "ok", "cached": False, "articles": mock_articles}

    url = f"https://newsdata.io/api/1/news?apikey={NEWSDATA_API_KEY}&category=business,top&language=en&size=10"
    
    try:
        import urllib.request
        import ssl

        def _fetch_news():
            import ssl as _ssl
            ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            req = urllib.request.Request(url, headers={"User-Agent": "Velure/3.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                return json.loads(resp.read().decode())

        data = await asyncio.get_event_loop().run_in_executor(None, _fetch_news)
        articles = data.get("results", [])
        formatted_articles = []
        for art in articles:
            formatted_articles.append({
                "title": art.get("title", ""),
                "link": art.get("link", ""),
                "source": art.get("source_id", "News"),
                "pubDate": art.get("pubDate", ""),
            })
        _news_cache["data"] = formatted_articles
        _news_cache["timestamp"] = now
        return {"status": "ok", "cached": False, "articles": formatted_articles}
    except Exception as e:
        api_log.error(f"News fetch error: {e}")
        return {"status": "error", "message": str(e), "articles": _news_cache["data"]}
