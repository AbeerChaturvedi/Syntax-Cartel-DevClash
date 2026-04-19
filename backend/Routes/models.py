from fastapi import APIRouter
from models.ensemble import ensemble

router = APIRouter()

@router.get("/api/scores")
async def get_latest_scores():
    """Get latest computed risk scores (REST fallback)."""
    scores = ensemble.get_latest_scores()
    if not scores:
        return {"status": "warming_up", "message": "Models are calibrating..."}
    return scores


@router.get("/api/merton")
async def get_merton_scores():
    """Get Distance-to-Default scores for all tracked institutions."""
    scores = ensemble.get_latest_scores()
    return scores.get("merton", [])


@router.get("/api/merton/debug")
async def get_merton_debug():
    """Internal state debug for Merton model."""
    from models.merton_model import merton_model as mm
    return {
        ticker: {
            "tick_count": mm._tick_count.get(ticker, 0),
            "price_buf_len": len(mm._price_buffers.get(ticker, [])),
            "vol_buf_len": len(mm._vol_buffers.get(ticker, [])),
            "ewma_var": mm._ewma_var.get(ticker, 0.0),
            "last_price": mm._price_buffers[ticker][-1] if mm._price_buffers.get(ticker) else None,
        }
        for ticker in mm.INSTITUTION_PROFILES
    }

@router.get("/api/merton/srisk")
async def get_system_srisk():
    """Get aggregate System SRISK — total capital shortfall across all institutions."""
    scores = ensemble.get_latest_scores()
    merton = scores.get("merton", [])
    total_srisk = sum(inst.get("srisk_bn", 0) for inst in merton)
    institutions = [
        {
            "ticker": inst["ticker"],
            "name": inst["name"],
            "srisk_bn": inst.get("srisk_bn", 0),
            "dd": inst.get("distance_to_default", 0),
            "pd": inst.get("prob_default", 0),
            "lrmes": inst.get("lrmes", 0),
            "status": inst.get("status", "UNKNOWN"),
        }
        for inst in merton
    ]
    return {
        "total_srisk_bn": round(total_srisk, 2),
        "institutions": institutions,
        "system_status": "CRITICAL" if total_srisk > 500 else "WARNING" if total_srisk > 200 else "HEALTHY",
    }


@router.get("/api/ciss/breakdown")
async def get_ciss_breakdown():
    """Get CISS component breakdown for explainability."""
    from models.ciss_scorer import ciss_scorer
    return ciss_scorer.get_breakdown()


@router.get("/api/var")
async def get_var_metrics():
    """Get Value-at-Risk and Conditional VaR metrics."""
    scores = ensemble.get_latest_scores()
    return scores.get("var_metrics", {})


@router.get("/api/copula")
async def get_copula_snapshot():
    """t-Copula tail-dependence snapshot: ρ matrix, λ_L matrix, ν, hot pair."""
    from models.copula_model import copula_model
    return copula_model.get_snapshot()
