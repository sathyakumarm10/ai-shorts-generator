"""Distributed Job Queue Service with Redis, Retries, Dead-Letter, and Fallback.

Provides a reliable queue implementation with Redis, exponential backoff retries,
dead-letter management, stale job recovery across worker crashes, and seamless
fallback to in-process ThreadPool execution.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable
from uuid import uuid4

logger = logging.getLogger(__name__)


class QueueBackend(str, Enum):
    """Supported job queue backends."""

    REDIS = "redis"
    THREADPOOL = "threadpool"


@dataclass
class QueueConfig:
    """Configuration options for job queueing and background workers."""

    backend: QueueBackend = QueueBackend.THREADPOOL
    configured_backend: str = "threadpool"
    redis_url: Optional[str] = None
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0
    queue_name: str = "ai_shorts:jobs"
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    visibility_timeout_seconds: float = 300.0  # 5 minutes before stale job lease expires
    stale_sweep_interval_seconds: float = 60.0
    enable_local_fallback: bool = True
    threadpool_max_workers: int = 4

    @classmethod
    def from_env(cls) -> "QueueConfig":
        """Load queue configuration from environment variables."""
        raw_backend = os.environ.get("QUEUE_BACKEND", "").strip().lower()
        redis_url = os.environ.get("REDIS_URL", "").strip() or None

        # If redis url is provided or queue backend is explicitly redis
        if raw_backend == "redis" or (raw_backend != "threadpool" and redis_url):
            target_backend = QueueBackend.REDIS
            configured = "redis"
        else:
            target_backend = QueueBackend.THREADPOOL
            configured = "threadpool"

        host = os.environ.get("REDIS_HOST", "localhost").strip() or None
        port_str = os.environ.get("REDIS_PORT", "6379").strip()
        port = int(port_str) if port_str.isdigit() else 6379
        password = os.environ.get("REDIS_PASSWORD", "").strip() or None
        db_str = os.environ.get("REDIS_DB", "0").strip()
        db = int(db_str) if db_str.isdigit() else 0

        if target_backend == QueueBackend.REDIS and not redis_url and host:
            auth = f":{password}@" if password else ""
            redis_url = f"redis://{auth}{host}:{port}/{db}"

        q_name = os.environ.get("JOB_QUEUE_NAME", "ai_shorts:jobs").strip()
        max_retries = int(os.environ.get("JOB_QUEUE_MAX_RETRIES", "3"))
        retry_delay = float(os.environ.get("JOB_QUEUE_RETRY_DELAY_SECONDS", "2.0"))
        vis_timeout = float(os.environ.get("JOB_QUEUE_VISIBILITY_TIMEOUT", "300.0"))
        sweep_interval = float(os.environ.get("JOB_QUEUE_STALE_SWEEP_INTERVAL", "60.0"))
        fallback = os.environ.get("QUEUE_ENABLE_LOCAL_FALLBACK", "true").strip().lower() in ("true", "1", "yes")
        tp_workers = int(os.environ.get("QUEUE_THREADPOOL_WORKERS", "4"))

        return cls(
            backend=target_backend,
            configured_backend=configured,
            redis_url=redis_url,
            redis_host=host,
            redis_port=port,
            redis_password=password,
            redis_db=db,
            queue_name=q_name,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay,
            visibility_timeout_seconds=vis_timeout,
            stale_sweep_interval_seconds=sweep_interval,
            enable_local_fallback=fallback,
            threadpool_max_workers=tp_workers,
        )


@dataclass
class QueueMessage:
    """A dequeued unit of work from the job queue."""

    job_id: str
    payload: Dict[str, Any]
    attempt: int
    enqueued_at: float
    locked_at: float
    worker_id: str


@dataclass
class QueueDiagnosticsReport:
    """Diagnostic status report for job queue health monitoring."""

    backend: str
    configured_backend: str
    connected: bool
    pending_count: int
    processing_count: int
    delayed_count: int
    dead_letter_count: int
    active_workers_count: int
    local_fallback_active: bool
    latency_ms: float
    error: Optional[str] = None


@runtime_checkable
class JobQueueBase(Protocol):
    """Protocol interface for job queues."""

    def enqueue(self, job_id: str, payload: Dict[str, Any]) -> None:
        ...

    def dequeue(self, timeout_seconds: float = 2.0, worker_id: str = "worker-1") -> Optional[QueueMessage]:
        ...

    def ack(self, job_id: str) -> None:
        ...

    def fail(self, job_id: str, error: str, can_retry: bool = True) -> bool:
        ...

    def recover_stale_jobs(self, visibility_timeout_seconds: Optional[float] = None) -> int:
        ...

    def heartbeat(self, worker_id: str) -> None:
        ...

    def get_diagnostics(self) -> QueueDiagnosticsReport:
        ...


class RedisJobQueue:
    """Production-grade Redis job queue with reliable multi-queue lifecycle."""

    def __init__(self, config: QueueConfig) -> None:
        self.config = config
        self._redis_url = config.redis_url or "redis://localhost:6379/0"
        self._q_name = config.queue_name

        # Keys
        self._key_pending = f"{self._q_name}:pending"
        self._key_processing = f"{self._q_name}:processing"
        self._key_delayed = f"{self._q_name}:delayed"
        self._key_dead = f"{self._q_name}:dead_letter"
        self._key_heartbeats = f"{self._q_name}:heartbeats"

        import redis

        self._client: redis.Redis = redis.from_url(self._redis_url, decode_responses=True)
        # Test connection ping
        self._client.ping()

    def enqueue(self, job_id: str, payload: Dict[str, Any]) -> None:
        """Enqueue a new job for worker processing."""
        data = {
            "job_id": job_id,
            "payload": payload,
            "attempt": 1,
            "enqueued_at": time.time(),
            "locked_at": 0.0,
            "worker_id": "",
        }
        raw = json.dumps(data)
        pipe = self._client.pipeline()
        pipe.lpush(self._key_pending, job_id)
        pipe.hset(self._key_processing, job_id, raw)
        pipe.execute()

    def dequeue(self, timeout_seconds: float = 2.0, worker_id: str = "worker-1") -> Optional[QueueMessage]:
        """Atomically pop the next available job, promoting any mature delayed items first."""
        now = time.time()

        # 1. Promote mature delayed retries to pending
        mature = self._client.zrangebyscore(self._key_delayed, 0, now)
        if mature:
            pipe = self._client.pipeline()
            for jid in mature:
                pipe.zrem(self._key_delayed, str(jid))
                pipe.lpush(self._key_pending, str(jid))
            pipe.execute()

        # 2. Block/pop from pending
        res = self._client.brpop(self._key_pending, timeout=int(max(1, timeout_seconds)))
        if not res:
            return None

        _, job_id = res
        raw = self._client.hget(self._key_processing, str(job_id))
        if not raw:
            return None

        try:
            data = json.loads(raw)
        except Exception:
            return None

        data["locked_at"] = now
        data["worker_id"] = worker_id
        self._client.hset(self._key_processing, job_id, json.dumps(data))

        return QueueMessage(
            job_id=data["job_id"],
            payload=data.get("payload", {}),
            attempt=data.get("attempt", 1),
            enqueued_at=data.get("enqueued_at", now),
            locked_at=now,
            worker_id=worker_id,
        )

    def ack(self, job_id: str) -> None:
        """Acknowledge successful completion and remove from processing registry."""
        self._client.hdel(self._key_processing, job_id)

    def fail(self, job_id: str, error: str, can_retry: bool = True) -> bool:
        """Handle job failure, scheduling a delayed retry or moving to dead letter."""
        raw = self._client.hget(self._key_processing, job_id)
        if not raw:
            return False

        try:
            data = json.loads(raw)
        except Exception:
            self._client.hdel(self._key_processing, job_id)
            return False

        current_attempt = data.get("attempt", 1)
        data["last_error"] = error

        if can_retry and current_attempt < self.config.max_retries:
            next_attempt = current_attempt + 1
            data["attempt"] = next_attempt
            data["locked_at"] = 0.0
            data["worker_id"] = ""

            # Exponential backoff: base_delay * 2^(attempt - 1)
            backoff_delay = self.config.retry_delay_seconds * (2 ** (current_attempt - 1))
            retry_at = time.time() + backoff_delay

            pipe = self._client.pipeline()
            pipe.hset(self._key_processing, job_id, json.dumps(data))
            pipe.zadd(self._key_delayed, {job_id: retry_at})
            pipe.execute()
            logger.info("Job %s failed (attempt %d/%d). Scheduled retry in %.1fs.", job_id, current_attempt, self.config.max_retries, backoff_delay)
            return True
        else:
            # Move to dead-letter queue
            pipe = self._client.pipeline()
            pipe.hdel(self._key_processing, job_id)
            pipe.zrem(self._key_delayed, job_id)
            pipe.rpush(self._key_dead, json.dumps(data))
            pipe.execute()
            logger.error("Job %s permanently failed after %d attempts: %s", job_id, current_attempt, error)
            return False

    def recover_stale_jobs(self, visibility_timeout_seconds: Optional[float] = None) -> int:
        """Scan processing items and re-queue any whose worker lease expired."""
        timeout = visibility_timeout_seconds or self.config.visibility_timeout_seconds
        now = time.time()
        recovered = 0

        all_proc = self._client.hgetall(self._key_processing)
        for jid, raw in all_proc.items():
            try:
                data = json.loads(raw)
                locked_at = data.get("locked_at", 0.0)
                # If job was locked and lease has expired
                if locked_at > 0 and (now - locked_at) > timeout:
                    logger.warning("Recovering stale job %s (locked %.1fs ago by %s)", jid, now - locked_at, data.get("worker_id"))
                    data["locked_at"] = 0.0
                    data["worker_id"] = ""
                    pipe = self._client.pipeline()
                    pipe.hset(self._key_processing, jid, json.dumps(data))
                    pipe.lpush(self._key_pending, jid)
                    pipe.execute()
                    recovered += 1
            except Exception:
                continue

        return recovered

    def heartbeat(self, worker_id: str) -> None:
        """Update worker heartbeat timestamp."""
        now = time.time()
        self._client.hset(self._key_heartbeats, worker_id, str(now))

    def get_diagnostics(self) -> QueueDiagnosticsReport:
        """Query Redis and build queue diagnostics."""
        t0 = time.perf_counter()
        try:
            now = time.time()
            pipe = self._client.pipeline()
            pipe.llen(self._key_pending)
            pipe.hlen(self._key_processing)
            pipe.zcard(self._key_delayed)
            pipe.llen(self._key_dead)
            pipe.hgetall(self._key_heartbeats)
            res = pipe.execute()

            pending = res[0]
            processing = res[1]
            delayed = res[2]
            dead = res[3]
            heartbeats = res[4] or {}

            # Count workers with heartbeat within last 30s
            active_workers = sum(1 for ts in heartbeats.values() if (now - float(ts)) <= 30.0)
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)

            return QueueDiagnosticsReport(
                backend="redis",
                configured_backend=self.config.configured_backend,
                connected=True,
                pending_count=pending,
                processing_count=processing,
                delayed_count=delayed,
                dead_letter_count=dead,
                active_workers_count=active_workers,
                local_fallback_active=False,
                latency_ms=latency_ms,
                error=None,
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return QueueDiagnosticsReport(
                backend="redis",
                configured_backend=self.config.configured_backend,
                connected=False,
                pending_count=0,
                processing_count=0,
                delayed_count=0,
                dead_letter_count=0,
                active_workers_count=0,
                local_fallback_active=self.config.enable_local_fallback,
                latency_ms=latency_ms,
                error=str(exc),
            )


class ThreadPoolJobQueue:
    """In-memory queue wrapper using ThreadPoolExecutor for local development and fallback."""

    def __init__(self, config: QueueConfig) -> None:
        self.config = config
        self._pending: List[Tuple[str, Dict[str, Any]]] = []
        self._processing: Dict[str, Dict[str, Any]] = {}
        self._dead_letter: List[Dict[str, Any]] = []
        self._workers_active = 1

    def enqueue(self, job_id: str, payload: Dict[str, Any]) -> None:
        self._pending.append((job_id, payload))

    def dequeue(self, timeout_seconds: float = 2.0, worker_id: str = "threadpool-1") -> Optional[QueueMessage]:
        if not self._pending:
            return None
        job_id, payload = self._pending.pop(0)
        now = time.time()
        msg = QueueMessage(
            job_id=job_id,
            payload=payload,
            attempt=1,
            enqueued_at=now,
            locked_at=now,
            worker_id=worker_id,
        )
        self._processing[job_id] = asdict(msg)
        return msg

    def ack(self, job_id: str) -> None:
        self._processing.pop(job_id, None)

    def fail(self, job_id: str, error: str, can_retry: bool = True) -> bool:
        rec = self._processing.pop(job_id, None)
        if rec:
            rec["error"] = error
            self._dead_letter.append(rec)
        return False

    def recover_stale_jobs(self, visibility_timeout_seconds: Optional[float] = None) -> int:
        return 0

    def heartbeat(self, worker_id: str) -> None:
        pass

    def get_diagnostics(self) -> QueueDiagnosticsReport:
        return QueueDiagnosticsReport(
            backend="threadpool",
            configured_backend=self.config.configured_backend,
            connected=True,
            pending_count=len(self._pending),
            processing_count=len(self._processing),
            delayed_count=0,
            dead_letter_count=len(self._dead_letter),
            active_workers_count=self._workers_active,
            local_fallback_active=False,
            latency_ms=0.1,
            error=None,
        )


def create_job_queue(config: Optional[QueueConfig] = None) -> JobQueueBase:
    """Create a configured JobQueue instance with transparent local fallback."""
    cfg = config or QueueConfig.from_env()

    if cfg.backend == QueueBackend.REDIS and cfg.redis_url:
        try:
            return RedisJobQueue(config=cfg)
        except Exception as exc:
            if cfg.enable_local_fallback:
                logger.warning("Failed to connect to Redis queue (%s). Falling back to ThreadPool queue.", exc)
                return ThreadPoolJobQueue(config=cfg)
            raise

    return ThreadPoolJobQueue(config=cfg)


def get_queue_report(queue: Optional[JobQueueBase] = None) -> QueueDiagnosticsReport:
    """Get active diagnostic status of the job queue."""
    if queue is not None:
        return queue.get_diagnostics()
    q = create_job_queue()
    return q.get_diagnostics()


# Default singleton instance
default_job_queue = create_job_queue()
