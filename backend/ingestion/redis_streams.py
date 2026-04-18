"""
Redis Streams — Event-driven message queue layer.
Decouples ingestion from inference to handle backpressure during high-velocity data.

Architecture:
    Simulator/Live Feed → Redis Stream (XADD) → Consumer Group (XREADGROUP) → ML Pipeline

Graceful Degradation:
    If Redis is unavailable, falls back to in-process queue (asyncio.Queue).
"""
import asyncio
import json
import time
import os
from typing import Optional, Dict, Callable, Any

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisStreamManager:
    """
    Manages Redis Streams for event-driven data pipeline.
    
    Streams:
        - stream:market_ticks   : Raw tick data from simulator/live feeds
        - stream:inference       : Processed inference results
        - stream:alerts          : Crisis alerts for persistence
    """

    STREAM_TICKS = "stream:market_ticks"
    STREAM_INFERENCE = "stream:inference"
    STREAM_ALERTS = "stream:alerts"
    CONSUMER_GROUP = "velure_workers"
    CONSUMER_NAME = "worker_1"

    # Max stream length to prevent unbounded memory growth
    MAX_STREAM_LEN = 10000
    # Trim strategy: approximate trim for performance
    TRIM_APPROXIMATE = True

    def __init__(self):
        self._redis: Optional[Any] = None
        self._connected = False
        self._fallback_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._use_fallback = False
        self._metrics = {
            "ticks_published": 0,
            "ticks_consumed": 0,
            "inference_published": 0,
            "alerts_published": 0,
            "fallback_mode": False,
            "redis_connected": False,
            "last_publish_ms": 0,
            "last_consume_ms": 0,
            "avg_latency_ms": 0.0,
            "latency_samples": [],
        }

    async def connect(self) -> bool:
        """Connect to Redis. Returns True if successful, False falls back to in-process."""
        if not REDIS_AVAILABLE:
            print("[REDIS] redis library not available, using in-process queue fallback")
            self._use_fallback = True
            self._metrics["fallback_mode"] = True
            return False

        redis_url = os.getenv("REDIS_URL", f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}")
        try:
            self._redis = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            self._connected = True
            self._metrics["redis_connected"] = True

            # Create consumer groups (idempotent)
            for stream in [self.STREAM_TICKS, self.STREAM_INFERENCE, self.STREAM_ALERTS]:
                try:
                    await self._redis.xgroup_create(
                        stream, self.CONSUMER_GROUP, id="0", mkstream=True
                    )
                except Exception:
                    pass  # Group already exists

            print(f"[REDIS] Connected to {redis_url}")
            return True

        except Exception as e:
            print(f"[REDIS] Connection failed ({e}), using in-process queue fallback")
            self._use_fallback = True
            self._metrics["fallback_mode"] = True
            return False

    async def disconnect(self):
        """Clean shutdown."""
        if self._redis and self._connected:
            await self._redis.aclose()
            self._connected = False

    async def publish_tick(self, tick_data: dict) -> str:
        """
        Publish a market tick to the stream.
        Returns the stream message ID.
        """
        start = time.monotonic()

        if self._use_fallback or not self._connected:
            # In-process fallback
            try:
                self._fallback_queue.put_nowait(tick_data)
            except asyncio.QueueFull:
                # Drop oldest — graceful degradation
                try:
                    self._fallback_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._fallback_queue.put_nowait(tick_data)
            self._metrics["ticks_published"] += 1
            return f"fallback-{self._metrics['ticks_published']}"

        try:
            # Serialize to flat dict for Redis Stream (values must be strings)
            payload = {
                "data": json.dumps(tick_data, default=str),
                "timestamp": str(tick_data.get("epoch_ms", int(time.time() * 1000))),
                "crisis_mode": str(tick_data.get("crisis_mode", False)),
            }
            msg_id = await self._redis.xadd(
                self.STREAM_TICKS,
                payload,
                maxlen=self.MAX_STREAM_LEN,
                approximate=self.TRIM_APPROXIMATE,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            self._metrics["ticks_published"] += 1
            self._metrics["last_publish_ms"] = round(elapsed_ms, 2)
            self._track_latency(elapsed_ms)
            return msg_id

        except Exception as e:
            # Fallback on Redis failure
            print(f"[REDIS] Publish failed: {e}, falling back")
            self._use_fallback = True
            self._metrics["fallback_mode"] = True
            return await self.publish_tick(tick_data)

    async def consume_tick(self, timeout_ms: int = 250) -> Optional[dict]:
        """
        Consume next tick from the stream.
        Uses consumer groups for exactly-once processing semantics.
        """
        start = time.monotonic()

        if self._use_fallback or not self._connected:
            try:
                tick = self._fallback_queue.get_nowait()
                self._metrics["ticks_consumed"] += 1
                return tick
            except asyncio.QueueEmpty:
                return None

        try:
            results = await self._redis.xreadgroup(
                groupname=self.CONSUMER_GROUP,
                consumername=self.CONSUMER_NAME,
                streams={self.STREAM_TICKS: ">"},
                count=1,
                block=timeout_ms,
            )

            if not results:
                return None

            for stream_name, messages in results:
                for msg_id, fields in messages:
                    tick_data = json.loads(fields["data"])

                    # ACK the message (exactly-once)
                    await self._redis.xack(
                        self.STREAM_TICKS, self.CONSUMER_GROUP, msg_id
                    )

                    elapsed_ms = (time.monotonic() - start) * 1000
                    self._metrics["ticks_consumed"] += 1
                    self._metrics["last_consume_ms"] = round(elapsed_ms, 2)
                    self._track_latency(elapsed_ms)
                    return tick_data

            return None

        except Exception as e:
            print(f"[REDIS] Consume failed: {e}")
            return None

    async def publish_inference(self, result: dict):
        """Publish inference results for caching/downstream consumers."""
        if not self._connected or self._use_fallback:
            return

        try:
            await self._redis.xadd(
                self.STREAM_INFERENCE,
                {"data": json.dumps(result, default=str)},
                maxlen=1000,
                approximate=True,
            )
            self._metrics["inference_published"] += 1

            # Also cache latest scores in a Redis key for REST fallback
            await self._redis.set(
                "velure:latest_scores",
                json.dumps(result, default=str),
                ex=30,  # 30s TTL
            )
        except Exception:
            pass

    async def publish_alert(self, alert: dict):
        """Publish crisis alerts to dedicated stream."""
        if not self._connected or self._use_fallback:
            return

        try:
            await self._redis.xadd(
                self.STREAM_ALERTS,
                {
                    "data": json.dumps(alert, default=str),
                    "severity": alert.get("severity", "UNKNOWN"),
                    "timestamp": str(alert.get("timestamp", "")),
                },
                maxlen=500,
            )
            self._metrics["alerts_published"] += 1
        except Exception:
            pass

    async def get_stream_info(self) -> dict:
        """Get stream metadata for system health monitoring."""
        if not self._connected or self._use_fallback:
            return {
                "mode": "in-process",
                "queue_size": self._fallback_queue.qsize(),
                "queue_capacity": self._fallback_queue.maxsize,
            }

        try:
            ticks_info = await self._redis.xinfo_stream(self.STREAM_TICKS)
            return {
                "mode": "redis-streams",
                "stream_length": ticks_info.get("length", 0),
                "first_entry": str(ticks_info.get("first-entry", "")),
                "last_entry": str(ticks_info.get("last-entry", "")),
                "consumer_groups": ticks_info.get("groups", 0),
            }
        except Exception:
            return {"mode": "redis-streams", "error": "info unavailable"}

    def _track_latency(self, latency_ms: float):
        """Track rolling average latency."""
        samples = self._metrics["latency_samples"]
        samples.append(latency_ms)
        if len(samples) > 100:
            self._metrics["latency_samples"] = samples[-100:]
        self._metrics["avg_latency_ms"] = round(
            sum(self._metrics["latency_samples"]) / len(self._metrics["latency_samples"]), 2
        )

    def get_metrics(self) -> dict:
        """Get pipeline metrics for system health dashboard."""
        return {
            "redis_connected": self._metrics["redis_connected"],
            "fallback_mode": self._metrics["fallback_mode"],
            "ticks_published": self._metrics["ticks_published"],
            "ticks_consumed": self._metrics["ticks_consumed"],
            "inference_published": self._metrics["inference_published"],
            "alerts_published": self._metrics["alerts_published"],
            "avg_latency_ms": self._metrics["avg_latency_ms"],
            "last_publish_ms": self._metrics["last_publish_ms"],
            "last_consume_ms": self._metrics["last_consume_ms"],
            "backlog": self._metrics["ticks_published"] - self._metrics["ticks_consumed"],
        }


# Singleton
redis_streams = RedisStreamManager()
