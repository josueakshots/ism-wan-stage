import json
import sqlite3
import time
import uuid
from contextlib import contextmanager


class Store:
    """One durable queue per API host. Tokens fence off expired workers."""
    def __init__(self, settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.data_dir / "jobs.sqlite3"
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request TEXT NOT NULL, prompt TEXT NOT NULL,
                image_id TEXT, state TEXT NOT NULL, created REAL NOT NULL,
                lease_token TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT, result TEXT, artifact_dir TEXT)""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def get(self, job_id):
        with self.connection() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def create(self, request, prompt, image_id):
        job_id = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            if count >= self.settings.max_active_jobs:
                raise OverflowError("Queue capacity reached")
            db.execute("INSERT INTO jobs(id,request,prompt,image_id,state,created) VALUES(?,?,?,?,?,?)",
                       (job_id, request.model_dump_json(), prompt, image_id, "queued", time.time()))
        return self.get(job_id)

    def claim(self):
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE jobs SET state=CASE WHEN attempts>=? THEN 'failed' ELSE 'queued' END,
                error=CASE WHEN attempts>=? THEN 'worker_lease_expired' ELSE NULL END,
                lease_token=NULL, lease_until=NULL WHERE state='running' AND lease_until<?""",
                (self.settings.max_attempts, self.settings.max_attempts, now))
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',lease_token=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                       (token, now + self.settings.lease_seconds, row["id"]))
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def owns(self, job_id, token):
        job = self.get(job_id)
        return bool(job and job["state"] == "running" and job["lease_token"] == token and job["lease_until"] > time.time())

    def heartbeat(self, job_id, token):
        with self.connection() as db:
            return db.execute("""UPDATE jobs SET lease_until=? WHERE id=? AND lease_token=?
                AND state='running' AND lease_until>?""",
                (time.time() + self.settings.lease_seconds, job_id, token, time.time())).rowcount == 1

    def finish(self, job_id, token, result=None, artifact_dir=None, error=None):
        with self.connection() as db:
            return db.execute("""UPDATE jobs SET state=?,result=?,artifact_dir=?,error=?,lease_token=NULL,
                lease_until=NULL WHERE id=? AND lease_token=? AND state='running' AND lease_until>?""",
                ("failed" if error else "succeeded", json.dumps(result) if result else None,
                 artifact_dir, error, job_id, token, time.time())).rowcount == 1
