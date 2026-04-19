import re

with open("backend/main.py", "r") as f:
    content = f.read()

# Clip at the start of routes
clip_idx = content.find("# ── Health Check (for Docker / Load Balancers) ──────────────────────")
if clip_idx != -1:
    content = content[:clip_idx]

# Remove global variable definitions at module level
content = re.sub(r'# ── Model lineage \+ audit hook ──────────────────────────────────────\n.*?\n_active_model_version = CHECKPOINT_VERSION\n_active_checkpoint_hash = "cold-start"\n', '', content, flags=re.DOTALL)

# Let's just import globals as g at the top
imports = """
from backend.globals import (
    manager, _asset_id_cache, _db_pool, _db_available,
    _pipeline_task, _checkpoint_task, _pipeline_running,
    _tick_rate, _data_mode, _finnhub, _last_crisis_ckpt_ts,
    _news_cache, _system_metrics, _active_model_version,
    _active_checkpoint_hash, _backtest_state, _replay_state
)
import backend.globals as g
"""
content = re.sub(r'from utils\.model_persistence import get_checkpoint_manager, CHECKPOINT_VERSION\n', 'from utils.model_persistence import get_checkpoint_manager, CHECKPOINT_VERSION\n' + imports, content)

# Now, replace `global var` declarations
content = re.sub(r'global\s+(_pipeline_running|_tick_rate|_db_available|_finnhub|_data_mode|_news_cache|_last_crisis_ckpt_ts|_active_model_version|_active_checkpoint_hash|_db_pool|_pipeline_task|_checkpoint_task)($|,|\s)+.*?\n', '', content)

# Replace specific assignments and reads for python primitive globals to use `g.`
to_replace = [
    '_pipeline_running', '_tick_rate', '_db_available', '_finnhub', '_data_mode',
    '_last_crisis_ckpt_ts', '_active_model_version', '_active_checkpoint_hash', 
    '_db_pool', '_pipeline_task', '_checkpoint_task'
]
for var in to_replace:
    # Use word boundary
    content = re.sub(r'\b' + var + r'\b', f'g.{var}', content)

# Since we imported mutable structures like _system_metrics, we don't strictly need to prefix with g. but we do need to remove their top-level definition
content = re.sub(r'_system_metrics = {.*?}# ── Connection Manager ──────────────────────────────────────────────.*?manager = ConnectionManager\(\)\n', '', content, flags=re.DOTALL)
content = re.sub(r'_news_cache = {"data": None, "timestamp": 0\.0}\n', '', content)
content = re.sub(r'_asset_id_cache = {}\n', '', content)

# Add Router Imports and Setup at the end
routers = """
from backend.Routes.system import router as system_router
from backend.Routes.models import router as models_router
from backend.Routes.stress import router as stress_router
from backend.Routes.websocket import router as websocket_router
from backend.Routes.news import router as news_router
from backend.Routes.portfolio import router as portfolio_router
from backend.Routes.historical import router as historical_router
from backend.Routes.backtest import router as backtest_router
from backend.Routes.replay import router as replay_router
from backend.Routes.audit import router as audit_router
from backend.Routes.Speed import router as speed_router

app.include_router(system_router)
app.include_router(models_router)
app.include_router(stress_router)
app.include_router(websocket_router)
app.include_router(news_router)
app.include_router(portfolio_router)
app.include_router(historical_router)
app.include_router(backtest_router)
app.include_router(replay_router)
app.include_router(audit_router)
app.include_router(speed_router)
"""

content += routers

with open("backend/main.py", "w") as f:
    f.write(content)
