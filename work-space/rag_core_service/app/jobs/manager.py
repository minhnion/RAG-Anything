from __future__ import annotations

import asyncio
import inspect
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas import JobProgress, JobRecord
from app.storage import PathStore, read_json, utc_now, write_json


JobCallable = Callable[[str], Awaitable[dict[str, Any]] | dict[str, Any]]
logger = logging.getLogger("rag_core_service.jobs")


class JobManager:
    def __init__(self, paths: PathStore):
        self.paths = paths
        self.logs_dir = self.paths.data_dir / "logs" / "jobs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._tasks: dict[str, asyncio.Task] = {}

    def create(
        self,
        workspace_id: str,
        document_id: str | None = None,
        request_id: str | None = None,
        result: dict[str, Any] | None = None,
        state: str = "pending",
    ) -> JobRecord:
        now = utc_now()
        job = JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:20]}",
            workspace_id=workspace_id,
            document_id=document_id,
            state=state,
            progress=JobProgress(stage=state, percent=100 if state == "completed" else 0),
            created_at=now,
            updated_at=now,
            request_id=request_id,
            result=result or {},
        )
        self.save(job)
        self._append_job_log(job.job_id, f"created workspace={workspace_id} document={document_id} state={state}")
        logger.info("Created job %s workspace=%s document=%s state=%s", job.job_id, workspace_id, document_id, state)
        return job

    def get(self, job_id: str) -> JobRecord | None:
        path = self.paths.job_path(job_id)
        if not path.exists():
            return None
        return JobRecord.model_validate(read_json(path, {}))

    def save(self, job: JobRecord) -> None:
        job.updated_at = utc_now()
        write_json(self.paths.job_path(job.job_id), job.model_dump())

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        stage: str | None = None,
        percent: int | None = None,
        message: str | None = None,
        error: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> JobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if state is not None:
            job.state = state
        if stage is not None:
            job.progress.stage = stage
        if percent is not None:
            job.progress.percent = max(0, min(100, int(percent)))
        if message is not None:
            job.progress.message = message
        if error is not None:
            job.error = error
        if result is not None:
            job.result = result
        self.save(job)
        line = (
            f"state={job.state} stage={job.progress.stage} "
            f"percent={job.progress.percent} message={job.progress.message}"
        )
        if error:
            line += f" error={error}"
        self._append_job_log(job_id, line)
        logger.info("Job %s %s", job_id, line)
        return job

    def start(self, job: JobRecord, func: JobCallable) -> None:
        async def runner() -> None:
            try:
                self.update(
                    job.job_id,
                    state="processing",
                    stage="pending",
                    percent=1,
                    message="Job accepted",
                )
                result = func(job.job_id)
                if inspect.isawaitable(result):
                    result = await result
                self.update(
                    job.job_id,
                    state="completed",
                    stage="completed",
                    percent=100,
                    message="Completed",
                    result=result or {},
                )
            except Exception as exc:  # pragma: no cover - exercised by integration runs
                tb = traceback.format_exc()
                self._append_job_log(job.job_id, tb)
                logger.exception("Job %s failed: %s", job.job_id, exc)
                self.update(
                    job.job_id,
                    state="failed",
                    stage="failed",
                    percent=100,
                    message=str(exc),
                    error=str(exc),
                    result={"traceback": tb},
                )

        self._tasks[job.job_id] = asyncio.create_task(runner())

    def job_log_path(self, job_id: str):
        return self.logs_dir / f"{job_id}.log"

    def _append_job_log(self, job_id: str, message: str) -> None:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with open(self.job_log_path(job_id), "a", encoding="utf-8") as f:
            f.write(f"{utc_now()} {message}\n")

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
