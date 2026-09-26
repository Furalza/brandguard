"""Background execution with per-source limits.

A small thread pool runs (scan, source) jobs. Each source has its own
concurrency cap because the sources fail differently: Google Play is an
unofficial scraper that throttles quickly, so one job at a time; Serper is a
paid API that tolerates a couple; crt.sh rate-limits by IP. Jobs are I/O
bound, so threads are enough; a separate worker process is a later step.

The pool holds no state that matters: every job re-reads its scan from the
database and writes its outcome there, so a crash loses nothing but the
in-flight requests.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from brandguard.api import scan_service

log = logging.getLogger("brandguard.api.worker")

SOURCE_LIMITS = {"play": 1, "serper": 2, "website": 2, "crtsh": 1}


class Worker:
    def __init__(self, max_workers: int = 4,
                 runner: Callable[[str, str], None] | None = None) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bg-scan")
        self._limits = {s: threading.Semaphore(n) for s, n in SOURCE_LIMITS.items()}
        self._run = runner or scan_service.run_scan_source
        self.inflight = 0
        self._lock = threading.Lock()

    def submit_scan(self, scan_id: str, sources: list[str]) -> None:
        for source in sources:
            self._pool.submit(self._job, scan_id, source)

    def _job(self, scan_id: str, source: str) -> None:
        sem = self._limits.get(source)
        with self._lock:
            self.inflight += 1
        try:
            if sem is not None:
                with sem:
                    self._run(scan_id, source)
            else:
                self._run(scan_id, source)
        except Exception:  # noqa: BLE001 - the runner records its own failures
            log.exception("job %s/%s crashed outside the runner", scan_id, source)
        finally:
            with self._lock:
                self.inflight -= 1

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)


class InlineWorker:
    """Runs jobs synchronously; used by tests and by the CLI runner."""

    def __init__(self, runner: Callable[[str, str], None] | None = None) -> None:
        self._run = runner or scan_service.run_scan_source
        self.inflight = 0

    def submit_scan(self, scan_id: str, sources: list[str]) -> None:
        for source in sources:
            self._run(scan_id, source)

    def shutdown(self, wait: bool = False) -> None:
        return None
