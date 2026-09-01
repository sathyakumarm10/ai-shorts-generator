"""Tests for the Redis and ThreadPool job queue implementations."""

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, call
import pytest

from app.services.queue_service import (
    QueueConfig,
    QueueBackend,
    QueueMessage,
    ThreadPoolJobQueue,
    create_job_queue,
)


# ---------------------------------------------------------------------------
# QueueConfig tests
# ---------------------------------------------------------------------------


class TestQueueConfig:
    def test_default_is_threadpool(self) -> None:
        cfg = QueueConfig()
        assert cfg.backend == QueueBackend.THREADPOOL

    def test_from_env_threadpool_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("QUEUE_BACKEND", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        cfg = QueueConfig.from_env()
        assert cfg.backend == QueueBackend.THREADPOOL

    def test_from_env_redis_via_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUEUE_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        cfg = QueueConfig.from_env()
        assert cfg.backend == QueueBackend.REDIS
        assert cfg.redis_url == "redis://localhost:6379/0"

    def test_from_env_redis_inferred_from_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("QUEUE_BACKEND", raising=False)
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        cfg = QueueConfig.from_env()
        assert cfg.backend == QueueBackend.REDIS

    def test_from_env_queue_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOB_QUEUE_NAME", "my_custom_queue")
        cfg = QueueConfig.from_env()
        assert cfg.queue_name == "my_custom_queue"

    def test_from_env_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOB_QUEUE_MAX_RETRIES", "5")
        cfg = QueueConfig.from_env()
        assert cfg.max_retries == 5

    def test_from_env_retry_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JOB_QUEUE_RETRY_DELAY_SECONDS", "60.0")
        cfg = QueueConfig.from_env()
        assert cfg.retry_delay_seconds == 60.0

    def test_from_env_builds_url_from_parts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUEUE_BACKEND", "redis")
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.setenv("REDIS_HOST", "redishost")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "s3cr3t")
        cfg = QueueConfig.from_env()
        assert cfg.redis_url is not None
        assert "redishost" in cfg.redis_url


# ---------------------------------------------------------------------------
# ThreadPoolJobQueue tests (no external deps required)
# ---------------------------------------------------------------------------


class TestThreadPoolJobQueue:
    def _queue(self) -> ThreadPoolJobQueue:
        cfg = QueueConfig(backend=QueueBackend.THREADPOOL)
        return ThreadPoolJobQueue(config=cfg)

    def test_enqueue_and_dequeue(self) -> None:
        q = self._queue()
        q.enqueue("job-1", {"type": "shorts"})
        msg = q.dequeue(timeout_seconds=0.1)
        assert msg is not None
        assert msg.job_id == "job-1"
        assert msg.payload == {"type": "shorts"}
        assert msg.attempt == 1

    def test_dequeue_empty_returns_none(self) -> None:
        q = self._queue()
        assert q.dequeue(timeout_seconds=0.1) is None

    def test_ack_removes_from_processing(self) -> None:
        q = self._queue()
        q.enqueue("job-ack", {})
        msg = q.dequeue()
        assert msg is not None
        q.ack(msg.job_id)
        diag = q.get_diagnostics()
        assert diag.processing_count == 0

    def test_fail_moves_to_dead_letter(self) -> None:
        q = self._queue()
        q.enqueue("job-fail", {"x": 1})
        msg = q.dequeue()
        assert msg is not None
        q.fail(msg.job_id, "something went wrong")
        diag = q.get_diagnostics()
        assert diag.dead_letter_count == 1
        assert diag.processing_count == 0

    def test_pending_count_tracks_enqueued(self) -> None:
        q = self._queue()
        for i in range(5):
            q.enqueue(f"job-{i}", {})
        diag = q.get_diagnostics()
        assert diag.pending_count == 5

    def test_recover_stale_jobs_returns_zero(self) -> None:
        q = self._queue()
        assert q.recover_stale_jobs() == 0

    def test_heartbeat_does_not_raise(self) -> None:
        q = self._queue()
        q.heartbeat("worker-1")  # Should be a no-op

    def test_diagnostics_backend_name(self) -> None:
        q = self._queue()
        diag = q.get_diagnostics()
        assert diag.backend == "threadpool"
        assert diag.connected is True

    def test_multiple_jobs_fifo_order(self) -> None:
        q = self._queue()
        for i in range(3):
            q.enqueue(f"job-{i}", {"seq": i})
        messages = []
        for _ in range(3):
            msg = q.dequeue()
            if msg:
                messages.append(msg.job_id)
        assert messages == ["job-0", "job-1", "job-2"]


# ---------------------------------------------------------------------------
# RedisJobQueue tests (mocked redis client)
# ---------------------------------------------------------------------------


def _make_redis_queue(mock_client: Any) -> "object":
    """Create a RedisJobQueue with a mocked Redis client bypassing ping."""
    from app.services.queue_service import RedisJobQueue

    cfg = QueueConfig(
        backend=QueueBackend.REDIS,
        redis_url="redis://localhost:6379/0",
        queue_name="test_queue",
        max_retries=3,
        retry_delay_seconds=2.0,
        visibility_timeout_seconds=300.0,
    )
    with patch("app.services.queue_service.RedisJobQueue.__init__", return_value=None):
        q: Any = RedisJobQueue.__new__(RedisJobQueue)
        q.config = cfg
        q._redis_url = "redis://localhost:6379/0"
        q._q_name = "test_queue"
        q._key_pending = "test_queue:pending"
        q._key_processing = "test_queue:processing"
        q._key_delayed = "test_queue:delayed"
        q._key_dead = "test_queue:dead_letter"
        q._key_heartbeats = "test_queue:heartbeats"
        q._client = mock_client
    return q


class TestRedisJobQueueEnqueue:
    """Tests for the enqueue operation."""

    def test_enqueue_pushes_to_pending_and_processing(self) -> None:
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = MagicMock(return_value=mock_pipe)
        mock_pipe.__exit__ = MagicMock(return_value=False)

        q = _make_redis_queue(mock_redis)
        q.enqueue("job-001", {"source": "test"})

        mock_pipe.lpush.assert_called_once_with("test_queue:pending", "job-001")
        assert mock_pipe.hset.call_count == 1
        hset_args = mock_pipe.hset.call_args
        assert hset_args[0][0] == "test_queue:processing"
        assert hset_args[0][1] == "job-001"
        data = json.loads(hset_args[0][2])
        assert data["job_id"] == "job-001"
        assert data["attempt"] == 1
        assert data["payload"] == {"source": "test"}


class TestRedisJobQueueAck:
    def test_ack_removes_from_processing(self) -> None:
        mock_redis = MagicMock()
        q = _make_redis_queue(mock_redis)
        q.ack("job-ack")
        mock_redis.hdel.assert_called_once_with("test_queue:processing", "job-ack")


class TestRedisJobQueueFail:
    def test_fail_schedules_retry_with_backoff(self) -> None:
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = MagicMock(return_value=mock_pipe)
        mock_pipe.__exit__ = MagicMock(return_value=False)

        data = json.dumps({
            "job_id": "job-retry",
            "attempt": 1,
            "payload": {},
            "enqueued_at": time.time(),
            "locked_at": time.time(),
            "worker_id": "w-1",
        })
        mock_redis.hget.return_value = data
        q = _make_redis_queue(mock_redis)

        result = q.fail("job-retry", "temporary failure", can_retry=True)
        assert result is True

        # Should update processing with incremented attempt and zadd to delayed
        mock_pipe.hset.assert_called()
        mock_pipe.zadd.assert_called()
        hset_call = mock_pipe.hset.call_args_list[0]
        updated_data = json.loads(hset_call[0][2])
        assert updated_data["attempt"] == 2

    def test_fail_moves_to_dead_letter_on_max_retries(self) -> None:
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = MagicMock(return_value=mock_pipe)
        mock_pipe.__exit__ = MagicMock(return_value=False)

        data = json.dumps({
            "job_id": "job-dead",
            "attempt": 3,  # = max_retries
            "payload": {},
            "enqueued_at": time.time(),
            "locked_at": time.time(),
            "worker_id": "w-1",
        })
        mock_redis.hget.return_value = data
        q = _make_redis_queue(mock_redis)

        result = q.fail("job-dead", "fatal error", can_retry=True)
        assert result is False

        # Should move to dead letter (hdel + rpush)
        mock_pipe.hdel.assert_called_once_with("test_queue:processing", "job-dead")
        mock_pipe.rpush.assert_called()
        assert "dead_letter" in mock_pipe.rpush.call_args[0][0]

    def test_fail_no_retry_goes_to_dead_letter_immediately(self) -> None:
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        data = json.dumps({
            "job_id": "job-nodeadline",
            "attempt": 1,
            "payload": {},
            "enqueued_at": time.time(),
            "locked_at": time.time(),
            "worker_id": "w-1",
        })
        mock_redis.hget.return_value = data
        q = _make_redis_queue(mock_redis)

        result = q.fail("job-nodeadline", "critical", can_retry=False)
        assert result is False
        mock_pipe.rpush.assert_called()

    def test_fail_exponential_backoff_delay(self) -> None:
        """Verify exponential backoff: base * 2^(attempt - 1)."""
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = MagicMock(return_value=mock_pipe)
        mock_pipe.__exit__ = MagicMock(return_value=False)

        for attempt in [1, 2]:
            data = json.dumps({
                "job_id": f"job-backoff-{attempt}",
                "attempt": attempt,
                "payload": {},
                "enqueued_at": time.time(),
                "locked_at": time.time(),
                "worker_id": "w-1",
            })
            mock_redis.hget.return_value = data
            q = _make_redis_queue(mock_redis)
            q.fail(f"job-backoff-{attempt}", "err", can_retry=True)

            # Extract zadd score (retry_at)
            zadd_call = mock_pipe.zadd.call_args
            if zadd_call:
                score_dict = zadd_call[0][1]
                retry_at = list(score_dict.values())[0]
                expected_delay = 2.0 * (2 ** (attempt - 1))
                actual_delay = retry_at - time.time()
                assert actual_delay == pytest.approx(expected_delay, abs=1.0)
            mock_pipe.reset_mock()

    def test_fail_returns_false_for_missing_job(self) -> None:
        mock_redis = MagicMock()
        mock_redis.hget.return_value = None
        q = _make_redis_queue(mock_redis)
        result = q.fail("ghost-job", "err")
        assert result is False


class TestRedisJobQueueRecovery:
    def test_recover_stale_jobs_re_queues_expired(self) -> None:
        import json

        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.__enter__ = MagicMock(return_value=mock_pipe)
        mock_pipe.__exit__ = MagicMock(return_value=False)

        stale_time = time.time() - 400  # 400s ago, older than 300s timeout
        fresh_time = time.time() - 10  # 10s ago, within timeout

        mock_redis.hgetall.return_value = {
            "stale-job": json.dumps({
                "job_id": "stale-job",
                "attempt": 1,
                "payload": {},
                "enqueued_at": stale_time,
                "locked_at": stale_time,
                "worker_id": "w-dead",
            }),
            "fresh-job": json.dumps({
                "job_id": "fresh-job",
                "attempt": 1,
                "payload": {},
                "enqueued_at": fresh_time,
                "locked_at": fresh_time,
                "worker_id": "w-alive",
            }),
        }

        q = _make_redis_queue(mock_redis)
        count = q.recover_stale_jobs(visibility_timeout_seconds=300.0)
        assert count == 1

        # stale-job should be re-pushed to pending
        push_calls = [c for c in mock_pipe.lpush.call_args_list
                      if "stale-job" in str(c)]
        assert len(push_calls) == 1

    def test_recover_stale_zero_when_all_fresh(self) -> None:
        import json

        mock_redis = MagicMock()
        fresh_time = time.time() - 5
        mock_redis.hgetall.return_value = {
            "fresh-job": json.dumps({
                "job_id": "fresh-job",
                "attempt": 1,
                "payload": {},
                "enqueued_at": fresh_time,
                "locked_at": fresh_time,
                "worker_id": "w-1",
            }),
        }
        q = _make_redis_queue(mock_redis)
        assert q.recover_stale_jobs(visibility_timeout_seconds=300.0) == 0


class TestRedisJobQueueHeartbeat:
    def test_heartbeat_sets_hash_entry(self) -> None:
        mock_redis = MagicMock()
        q = _make_redis_queue(mock_redis)
        q.heartbeat("worker-99")
        mock_redis.hset.assert_called_once_with(
            "test_queue:heartbeats", "worker-99", mock_redis.hset.call_args[0][2]
        )


class TestRedisJobQueueDiagnostics:
    def test_diagnostics_happy_path(self) -> None:
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe

        now = time.time()
        mock_pipe.execute.return_value = [
            5,   # pending llen
            2,   # processing hlen
            1,   # delayed zcard
            0,   # dead_letter llen
            {"w-1": str(now - 5), "w-2": str(now - 40)},  # heartbeats (w-2 is stale)
        ]
        q = _make_redis_queue(mock_redis)
        diag = q.get_diagnostics()

        assert diag.backend == "redis"
        assert diag.connected is True
        assert diag.pending_count == 5
        assert diag.processing_count == 2
        assert diag.delayed_count == 1
        assert diag.dead_letter_count == 0
        assert diag.active_workers_count == 1  # only w-1 is within 30s window
        assert diag.error is None

    def test_diagnostics_on_redis_error(self) -> None:
        mock_redis = MagicMock()
        mock_pipe = MagicMock()
        mock_redis.pipeline.return_value = mock_pipe
        mock_pipe.execute.side_effect = Exception("connection refused")

        q = _make_redis_queue(mock_redis)
        diag = q.get_diagnostics()

        assert diag.connected is False
        assert diag.error is not None
        assert "connection refused" in diag.error


# ---------------------------------------------------------------------------
# create_job_queue factory fallback tests
# ---------------------------------------------------------------------------


class TestCreateJobQueueFactory:
    def test_threadpool_fallback_when_redis_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.queue_service import ThreadPoolJobQueue

        monkeypatch.setenv("QUEUE_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://invalid_host:9999/0")
        monkeypatch.setenv("QUEUE_ENABLE_LOCAL_FALLBACK", "true")

        q = create_job_queue()
        # Should have fallen back to ThreadPool
        assert isinstance(q, ThreadPoolJobQueue)

    def test_raises_when_fallback_disabled_and_redis_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QUEUE_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://invalid_host:9999/0")
        monkeypatch.setenv("QUEUE_ENABLE_LOCAL_FALLBACK", "false")

        with pytest.raises(Exception):
            create_job_queue()

    def test_threadpool_when_no_redis_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.services.queue_service import ThreadPoolJobQueue

        monkeypatch.delenv("QUEUE_BACKEND", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        q = create_job_queue()
        assert isinstance(q, ThreadPoolJobQueue)
