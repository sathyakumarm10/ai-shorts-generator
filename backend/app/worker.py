"""Background Worker Daemon for Distributed AI Shorts Generation.

Consumes jobs from the Redis queue, executes video processing pipelines, handles
automatic retries with exponential backoff, records permanent failures to dead-letter,
and recovers stale jobs from dead worker instances.
"""

import logging
import os
import signal
import sys
import time
from typing import Optional
from uuid import uuid4

from app.models import ShortsGenerationRequest
from app.services.job_runner_service import JobRunnerService, default_job_runner
from app.services.job_service import default_job_service
from app.services.queue_service import (
    JobQueueBase,
    QueueConfig,
    create_job_queue,
    default_job_queue,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("shorts_worker")


class ShortsWorker:
    """Worker daemon processing jobs from Redis queue."""

    def __init__(
        self,
        worker_id: Optional[str] = None,
        queue: Optional[JobQueueBase] = None,
        job_runner: Optional[JobRunnerService] = None,
        sweep_interval_seconds: float = 60.0,
    ) -> None:
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.queue = queue if queue is not None else default_job_queue
        self.job_runner = job_runner or default_job_runner
        self.sweep_interval = sweep_interval_seconds
        self._running = False
        self._last_sweep = 0.0

    def start(self) -> None:
        """Start the worker processing loop."""
        self._running = True
        logger.info("Starting ShortsWorker [%s] on queue %s", self.worker_id, getattr(self.queue, "_q_name", "local"))

        # Setup graceful signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        while self._running:
            try:
                # 1. Update heartbeat
                self.queue.heartbeat(self.worker_id)

                # 2. Periodic stale job recovery
                now = time.time()
                if now - self._last_sweep >= self.sweep_interval:
                    self._last_sweep = now
                    recovered = self.queue.recover_stale_jobs()
                    if recovered > 0:
                        logger.info("Worker [%s] recovered %d stale job(s)", self.worker_id, recovered)

                # 3. Dequeue next job
                msg = self.queue.dequeue(timeout_seconds=2.0, worker_id=self.worker_id)
                if not msg:
                    continue

                logger.info(
                    "Worker [%s] picked up job %s (attempt %d)",
                    self.worker_id,
                    msg.job_id,
                    msg.attempt,
                )

                # 4. Execute pipeline
                try:
                    request = ShortsGenerationRequest.model_validate(msg.payload)
                    self.job_runner.execute_job_pipeline(msg.job_id, request)
                    self.queue.ack(msg.job_id)
                    logger.info("Worker [%s] successfully finished job %s", self.worker_id, msg.job_id)

                except Exception as exc:
                    err_msg = str(exc)
                    logger.warning("Worker [%s] error processing job %s: %s", self.worker_id, msg.job_id, err_msg)
                    will_retry = self.queue.fail(msg.job_id, err_msg, can_retry=True)
                    if will_retry:
                        logger.info("Worker [%s] scheduled retry for job %s", self.worker_id, msg.job_id)
                    else:
                        logger.error("Worker [%s] job %s permanently failed", self.worker_id, msg.job_id)

            except Exception as exc:
                logger.error("Worker [%s] unexpected loop exception: %s", self.worker_id, exc)
                time.sleep(1.0)

        logger.info("Worker [%s] stopped gracefully.", self.worker_id)

    def stop(self) -> None:
        """Signal the worker to stop after current iteration."""
        self._running = False

    def _handle_signal(self, signum: int, frame: object) -> None:
        logger.info("Received termination signal %d. Stopping worker [%s]...", signum, self.worker_id)
        self.stop()


def main() -> None:
    """Entry point for standalone worker container."""
    worker = ShortsWorker()
    worker.start()


if __name__ == "__main__":
    main()
