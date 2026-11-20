import logging
from time import time

from celery import Celery
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError

from agents.supervisor import checkpointer, run_research
from app.config import settings
from app.db import Session
from app.models import Asset, Job, JobEvent, Login, Project
from app.reports import MIME, render
from app.storage import put, remove
from ingestion.service import ingest

logger = logging.getLogger(__name__)
celery = Celery("researchpilot", broker=settings().redis_url or "memory://")
celery.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
                   task_ignore_result=True, broker_connection_retry_on_startup=True,
                   beat_schedule={"recover-jobs": {"task": "app.worker.recover", "schedule": 60}})


def run_job(job_id):
    with Session() as db:
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued")
                             .values(status="running", updated=time())).rowcount
        db.commit()
        if not claimed:
            return
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            if job.kind == "ingest":
                status, result = "succeeded", ingest(db, job)
            elif job.kind == "research":
                status, result = run_research(db, job)
            elif job.kind == "purge":
                purge(db, job.project_id)
                db.commit()
                return
            elif job.kind == "report":
                original = db.scalar(select(Job).where(Job.id == job.payload["research_id"],
                                                       Job.project_id == job.project_id, Job.status == "succeeded"))
                if original is None or original.kind != "research":
                    raise ValueError("Research run unavailable")
                keys = {}
                for output_type, (_, suffix) in MIME.items():
                    key = f"{job.project_id}/reports/{job.id}.{suffix}"
                    put(key, render(job.payload["title"], original.result, output_type))
                    keys[output_type] = key
                status, result = "succeeded", {"formats": list(keys), "keys": keys}
            else:
                raise ValueError("Unsupported job")
            job.status, job.result = status, result
            db.add(JobEvent(job_id=job.id, stage=status))
            db.commit()
        except OperationalError:
            db.rollback()
            raise
        except Exception as exc:
            db.rollback()
            logger.error("job_failed id=%s type=%s", job_id, type(exc).__name__)
            job = db.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error = str(exc) if isinstance(exc, (ValueError, TimeoutError)) else "Job failed while processing input"
                db.add(JobEvent(job_id=job.id, stage="failed"))
                db.commit()


@celery.task(bind=True, time_limit=150, max_retries=2, name="app.worker.execute")
def execute(self, job_id):
    try:
        run_job(job_id)
    except OperationalError:
        with Session() as db:
            db.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(status="queued"))
            db.commit()
        raise self.retry(exc=RuntimeError("Database temporarily unavailable"), countdown=2 ** self.request.retries) from None


@celery.task(name="app.worker.recover")
def recover():
    with Session() as db:
        db.execute(delete(Login).where(Login.expires < time()))
        cutoff = time() - 240
        db.execute(update(Job).where(Job.status == "running", Job.updated < cutoff)
                   .values(status="failed", error="Worker stopped before job completion"))
        candidates = db.scalars(select(Job.id).where(Job.status == "queued", Job.updated < time() - 30).limit(100)).all()
        db.commit()
    for job_id in candidates:
        execute.delay(job_id)


def schedule(tasks, job_id):
    if settings().redis_url:
        try:
            execute.apply_async(args=(job_id,), retry=False)
        except Exception:
            logger.error("queue_dispatch_pending id=%s", job_id)
    else:
        tasks.add_task(run_job, job_id)


def purge(db, project_id):
    project = db.get(Project, project_id)
    if project is None or not project.pending_deletion:
        raise ValueError("Project is unavailable for deletion")
    for asset in db.scalars(select(Asset).where(Asset.project_id == project_id)):
        remove(asset.key)
    jobs = db.scalars(select(Job).where(Job.project_id == project_id, Job.kind.in_(("report", "research"))))
    with checkpointer() as saver:
        for job in jobs:
            if job.kind == "report":
                for _, suffix in MIME.values():
                    remove(f"{project_id}/reports/{job.id}.{suffix}")
            else:
                saver.delete_thread(job.id)
    db.delete(project)
