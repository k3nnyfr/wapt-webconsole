"""Background jobs (store imports): progress per item, read by the browser while the job runs.

Jobs live in memory: a restart of the backend forgets them (the audit journal keeps their outcome).
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field

KEEP = 50


@dataclass
class JobItem:
    name: str
    version: str
    target: str
    size: int
    reason: str = "requested"
    filename: str = ""
    md5sum: str = ""
    status: str = "waiting"        # waiting, downloading, signing, uploading, done, error
    progress: float = 0.0
    error: str = ""
    imported_version: str = ""


@dataclass
class Job:
    id: str
    user: str
    kind: str
    items: list[JobItem]
    created: float = field(default_factory=time.time)
    status: str = "running"        # running, done, failed
    message: str = ""
    finished: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class Jobs:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def start(self, user: str, kind: str, items: list[JobItem], run: Callable[[Job], Awaitable[str]]) -> Job:
        job = Job(secrets.token_urlsafe(8), user, kind, items)
        self.jobs[job.id] = job
        for old in sorted(self.jobs.values(), key=lambda j: j.created)[:-KEEP]:
            if old.status != "running":
                del self.jobs[old.id]

        async def wrapper():
            try:
                job.message = await run(job)
                job.status = "failed" if any(i.status == "error" for i in job.items) else "done"
            except Exception as e:        # the job reports its failure instead of dying silently
                job.status, job.message = "failed", str(e)
                for item in job.items:
                    if item.status not in ("done", "error"):
                        item.status, item.error = "error", str(e)
            finally:
                job.finished = time.time()

        task = asyncio.create_task(wrapper())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def recent(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
