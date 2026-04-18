"""
Multi-sink alert dispatcher.

When the ensemble flags HIGH/CRITICAL, the alert has to leave the box.
A WebSocket broadcast and an in-memory deque are not enough for a
system that's supposed to wake a human up.

Sinks supported:
    · Slack Incoming Webhook
    · Discord Webhook
    · PagerDuty Events API v2 (Routing Key)
    · Generic JSON webhook (Opsgenie, VictorOps, custom bus)
    · SMTP email (configurable FROM/TO + TLS)

Design:
    · All sinks are fire-and-forget async tasks → they never block
      the inference loop.
    · A short-window dedup key (default 5 min) prevents a flapping
      score from hammering the humans with identical alerts.
    · Severity routing: a minimum severity gate (default HIGH) is
      enforced at the dispatcher; per-sink overrides are supported.
    · Every delivery attempt is logged.  Failures do not raise.
"""
import asyncio
import json
import smtplib
import time
from email.message import EmailMessage
from typing import Dict, List, Optional

import aiohttp

from utils.config import (
    ALERT_SLACK_WEBHOOK,
    ALERT_DISCORD_WEBHOOK,
    ALERT_PAGERDUTY_KEY,
    ALERT_GENERIC_WEBHOOK,
    ALERT_EMAIL_SMTP_HOST,
    ALERT_EMAIL_SMTP_PORT,
    ALERT_EMAIL_SMTP_USER,
    ALERT_EMAIL_SMTP_PASSWORD,
    ALERT_EMAIL_FROM,
    ALERT_EMAIL_TO,
    ALERT_DEDUP_WINDOW_SEC,
    ALERT_MIN_SEVERITY,
)
from utils.logger import api_log


_SEVERITY_RANK = {
    "NORMAL":   0,
    "LOW":      1,
    "MEDIUM":   2,
    "HIGH":     3,
    "CRITICAL": 4,
}


class AlertDispatcher:
    """Fans alerts out to configured sinks with dedup + severity routing."""

    def __init__(self):
        self._dedup_store: Dict[str, float] = {}
        self._min_rank = _SEVERITY_RANK.get(ALERT_MIN_SEVERITY, 3)
        self._delivery_count = 0
        self._failure_count = 0
        self._last_error: Optional[str] = None
        # Optional audit hook — wired by main.py to write to audit_log.
        # Async callable: (alert: dict, dispatch_result: dict) -> None
        self._audit_sink = None

    def set_audit_sink(self, sink):
        """Register an async callable that receives every dispatch outcome."""
        self._audit_sink = sink

    # ── public entrypoint ──────────────────────────────────────────
    async def dispatch(self, alert: dict) -> Dict:
        """Send an alert through all configured sinks."""
        severity = (alert.get("severity") or "NORMAL").upper()
        rank = _SEVERITY_RANK.get(severity, 0)
        if rank < self._min_rank:
            return {"delivered": False, "reason": f"below min severity ({ALERT_MIN_SEVERITY})"}

        key = self._dedup_key(alert)
        if self._is_dedup(key):
            return {"delivered": False, "reason": "deduplicated"}
        self._dedup_store[key] = time.time()

        results: Dict[str, Dict] = {}
        tasks = []
        if ALERT_SLACK_WEBHOOK:
            tasks.append(("slack", self._send_slack(alert)))
        if ALERT_DISCORD_WEBHOOK:
            tasks.append(("discord", self._send_discord(alert)))
        if ALERT_PAGERDUTY_KEY:
            tasks.append(("pagerduty", self._send_pagerduty(alert)))
        if ALERT_GENERIC_WEBHOOK:
            tasks.append(("webhook", self._send_generic_webhook(alert)))
        if ALERT_EMAIL_SMTP_HOST and ALERT_EMAIL_TO:
            tasks.append(("email", self._send_email(alert)))

        if not tasks:
            return {"delivered": False, "reason": "no sinks configured"}

        coro_results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
        for (name, _), res in zip(tasks, coro_results):
            if isinstance(res, Exception):
                results[name] = {"ok": False, "error": str(res)}
                self._failure_count += 1
                self._last_error = f"{name}: {res}"
            else:
                results[name] = res
                if res.get("ok"):
                    self._delivery_count += 1

        api_log.info("alert dispatched", extra={"severity": severity, "sinks": list(results.keys())})
        outcome = {"delivered": True, "sinks": results}

        # Persist to audit_log if a sink is registered. Failure here is logged
        # but never surfaced — alerts must never fail because the audit DB is
        # down. Operators detect missing audit rows via the readiness check.
        if self._audit_sink is not None:
            try:
                await self._audit_sink(alert, outcome)
            except Exception as e:
                api_log.warning(f"audit_sink failed: {e}")

        return outcome

    def status(self) -> Dict:
        return {
            "delivery_count": self._delivery_count,
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "sinks_enabled": {
                "slack": bool(ALERT_SLACK_WEBHOOK),
                "discord": bool(ALERT_DISCORD_WEBHOOK),
                "pagerduty": bool(ALERT_PAGERDUTY_KEY),
                "webhook": bool(ALERT_GENERIC_WEBHOOK),
                "email": bool(ALERT_EMAIL_SMTP_HOST and ALERT_EMAIL_TO),
            },
            "min_severity": ALERT_MIN_SEVERITY,
            "dedup_window_sec": ALERT_DEDUP_WINDOW_SEC,
        }

    async def test_alert(self, severity: str = "HIGH") -> Dict:
        """Send a synthetic alert through all sinks for verification."""
        self._dedup_store.clear()  # bypass dedup for tests
        return await self.dispatch({
            "severity": severity,
            "type": "TEST_ALERT",
            "message": "Project Velure test alert — if you're seeing this, alerting works.",
            "score": 0.99,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    # ── internals ──────────────────────────────────────────────────
    def _dedup_key(self, alert: dict) -> str:
        return f"{alert.get('type', 'X')}:{alert.get('severity', 'X')}"

    def _is_dedup(self, key: str) -> bool:
        now = time.time()
        # Prune expired entries
        for k in list(self._dedup_store.keys()):
            if now - self._dedup_store[k] > ALERT_DEDUP_WINDOW_SEC:
                self._dedup_store.pop(k, None)
        return key in self._dedup_store

    @staticmethod
    def _format_text(alert: dict) -> str:
        sev = alert.get("severity", "?")
        atype = alert.get("type", "?")
        score = alert.get("score", "?")
        msg = alert.get("message", "")
        ts = alert.get("timestamp", "")
        return f"[{sev}] {atype} — score={score} @ {ts}\n{msg}"

    # Slack — Incoming Webhook
    async def _send_slack(self, alert: dict) -> Dict:
        text = self._format_text(alert)
        color = "#ef4444" if alert.get("severity") == "CRITICAL" else "#f97316"
        payload = {
            "attachments": [{
                "color": color,
                "title": f"Project Velure — {alert.get('severity')} alert",
                "text": text,
                "fields": [
                    {"title": "Type", "value": alert.get("type", "?"), "short": True},
                    {"title": "Score", "value": str(alert.get("score", "?")), "short": True},
                ],
                "ts": int(time.time()),
            }],
        }
        return await self._post_json(ALERT_SLACK_WEBHOOK, payload)

    # Discord — webhook JSON
    async def _send_discord(self, alert: dict) -> Dict:
        payload = {
            "username": "Velure Crisis Monitor",
            "embeds": [{
                "title": f"{alert.get('severity')} — {alert.get('type')}",
                "description": alert.get("message", ""),
                "color": 0xef4444 if alert.get("severity") == "CRITICAL" else 0xf97316,
                "fields": [{"name": "Score", "value": str(alert.get("score", "?"))}],
                "timestamp": alert.get("timestamp", ""),
            }],
        }
        return await self._post_json(ALERT_DISCORD_WEBHOOK, payload)

    # PagerDuty Events v2
    async def _send_pagerduty(self, alert: dict) -> Dict:
        payload = {
            "routing_key": ALERT_PAGERDUTY_KEY,
            "event_action": "trigger",
            "dedup_key": self._dedup_key(alert),
            "payload": {
                "summary": f"Velure {alert.get('severity')} — {alert.get('type')}",
                "source": "project-velure",
                "severity": "critical" if alert.get("severity") == "CRITICAL" else "error",
                "custom_details": alert,
            },
        }
        return await self._post_json("https://events.pagerduty.com/v2/enqueue", payload)

    # Generic webhook
    async def _send_generic_webhook(self, alert: dict) -> Dict:
        return await self._post_json(ALERT_GENERIC_WEBHOOK, alert)

    # Email via SMTP (sync smtplib, run off-loop)
    async def _send_email(self, alert: dict) -> Dict:
        def _send_sync():
            msg = EmailMessage()
            msg["From"] = ALERT_EMAIL_FROM or ALERT_EMAIL_SMTP_USER
            msg["To"] = ALERT_EMAIL_TO
            msg["Subject"] = f"[Velure/{alert.get('severity')}] {alert.get('type')}"
            msg.set_content(self._format_text(alert))
            with smtplib.SMTP(ALERT_EMAIL_SMTP_HOST, ALERT_EMAIL_SMTP_PORT, timeout=10) as s:
                s.starttls()
                if ALERT_EMAIL_SMTP_USER:
                    s.login(ALERT_EMAIL_SMTP_USER, ALERT_EMAIL_SMTP_PASSWORD)
                s.send_message(msg)
            return True

        try:
            await asyncio.to_thread(_send_sync)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _post_json(self, url: str, payload: dict) -> Dict:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.post(url, json=payload) as resp:
                    body_preview = (await resp.text())[:200]
                    return {
                        "ok": 200 <= resp.status < 300,
                        "status": resp.status,
                        "body_preview": body_preview,
                    }
        except Exception as e:
            return {"ok": False, "error": str(e)}


# Singleton
alert_dispatcher = AlertDispatcher()
