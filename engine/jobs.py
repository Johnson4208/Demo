"""Bounded in-process job queue for the supported single-instance deployment."""

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Lock

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="solvai-job")
_LOCK = Lock()
_JOBS = {}
MAX_JOB_HISTORY = 250


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def submit(kind, function, *args, owner_user_id=None, **kwargs):
    job_id = secrets.token_urlsafe(16)
    with _LOCK:
        if len(_JOBS) >= MAX_JOB_HISTORY:
            finished = [key for key, value in _JOBS.items() if value.get("status") in {"complete", "failed"}]
            for old_id in finished[:max(1, len(_JOBS) - MAX_JOB_HISTORY + 1)]:
                _JOBS.pop(old_id, None)
        _JOBS[job_id] = {"id": job_id, "kind": str(kind), "status": "queued", "owner_user_id": owner_user_id,
                         "created_at": _now(), "started_at": None, "finished_at": None, "result": None, "error": None}

    def run():
        with _LOCK:
            _JOBS[job_id]["status"] = "running"; _JOBS[job_id]["started_at"] = _now()
        try:
            result = function(*args, **kwargs)
            with _LOCK:
                _JOBS[job_id]["status"] = "complete"; _JOBS[job_id]["result"] = result
        except Exception as exc:
            with _LOCK:
                _JOBS[job_id]["status"] = "failed"; _JOBS[job_id]["error"] = str(exc)[:500]
        finally:
            with _LOCK:
                _JOBS[job_id]["finished_at"] = _now()

    _EXECUTOR.submit(run)
    return public_job(job_id, owner_user_id=owner_user_id, is_admin=True)


def public_job(job_id, *, owner_user_id=None, is_admin=False):
    with _LOCK:
        job = dict(_JOBS.get(str(job_id)) or {})
    if not job:
        return None
    if not is_admin and owner_user_id is not None and int(job.get("owner_user_id") or -1) != int(owner_user_id):
        return None
    job.pop("owner_user_id", None)
    return job
