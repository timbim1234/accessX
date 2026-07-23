"""In-memory job store with a background worker thread per job.

Jobs run one at a time (global worker lock). State lives in a dict guarded by
a threading.Lock; the FastAPI layer only reads copies.
"""
from __future__ import annotations

import copy
import threading
import time
import traceback
import uuid
from typing import Any, Dict, List, Optional

import analysis

_WORKER_LOCK = threading.Lock()  # serializes job execution


class _JobReporter(analysis.NullReporter):
    """Publishes stage progress into the job dict (thread-safe via store lock)."""

    def __init__(self, store: "JobStore", job_id: str) -> None:
        self._store = store
        self._job_id = job_id

    def _set(self, key: str, **updates: Any) -> None:
        with self._store._lock:
            job = self._store._jobs.get(self._job_id)
            if job is None:
                return
            for stage in job["stages"]:
                if stage["key"] == key:
                    stage.update(updates)
                    return

    def start(self, key: str) -> None:
        self._set(key, status="running")

    def done(self, key: str, seconds: float, detail: Optional[str] = None) -> None:
        self._set(key, status="done", seconds=round(float(seconds), 2), detail=detail)

    def skip(self, key: str, detail: Optional[str] = None) -> None:
        self._set(key, status="skipped", detail=detail)

    def warn(self, message: str) -> None:
        with self._store._lock:
            job = self._store._jobs.get(self._job_id)
            if job is not None:
                job["warnings"].append(message)


class JobStore:
    """In-memory registry of analysis jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, dict] = {}

    def create(self, params: dict) -> str:
        """Register a job and start its worker thread. Returns the job id."""
        job_id = uuid.uuid4().hex[:12]
        stages: List[dict] = [
            {"key": key, "label": label, "status": "pending", "seconds": None, "detail": None}
            for key, label in analysis.STAGES
        ]
        job = {
            "job_id": job_id,
            "status": "queued",
            "stages": stages,
            "warnings": [],
            "error": None,
            "result": None,
            "graph": None,
            "hexes_m": None,
            "params": params,
            "created": time.time(),
        }
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        thread.start()
        return job_id

    def get(self, job_id: str) -> Optional[dict]:
        with self._lock:
            return self._jobs.get(job_id)

    def public_status(self, job_id: str) -> Optional[dict]:
        """Contract-shaped status payload (safe copy), or None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return {
                "job_id": job["job_id"],
                "status": job["status"],
                "stages": copy.deepcopy(job["stages"]),
                "warnings": list(job["warnings"]),
                "error": job["error"],
            }

    @staticmethod
    def _close_unfinished_stages(job: dict) -> None:
        """On job error: no stage may stay 'running'/'pending' forever."""
        for stage in job["stages"]:
            if stage["status"] in ("running", "pending"):
                stage["status"] = "skipped"
                stage["detail"] = "afgebroken door fout"

    def _run(self, job_id: str) -> None:
        with _WORKER_LOCK:
            job = self.get(job_id)
            if job is None:
                return
            with self._lock:
                job["status"] = "running"
            reporter = _JobReporter(self, job_id)
            try:
                output = analysis.run_pipeline(job["params"], reporter)
                with self._lock:
                    job["result"] = output["result"]
                    job["graph"] = output["graph"]
                    job["hexes_m"] = output["hexes_m"]
                    job["status"] = "done"
            except analysis.PipelineError as exc:
                traceback.print_exc()
                with self._lock:
                    job["status"] = "error"
                    job["error"] = str(exc)
                    self._close_unfinished_stages(job)
            except Exception as exc:  # noqa: BLE001 - report any failure to the user
                traceback.print_exc()
                with self._lock:
                    job["status"] = "error"
                    job["error"] = f"Onverwachte fout tijdens de analyse: {exc}"
                    self._close_unfinished_stages(job)
