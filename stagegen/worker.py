import argparse
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .backends import generate

log = logging.getLogger("stagegen.worker")


class Worker:
    def __init__(self, url, key, backend, work_dir, transport=None):
        parsed = urlparse(url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "api", "testserver"}):
            raise ValueError("Use HTTPS for a remote API")
        if len(key) < 24:
            raise ValueError("A worker credential of at least 24 characters is required")
        if backend not in {"preview", "wan-native"}:
            raise ValueError("Unknown backend")
        self.url, self.key, self.backend = url.rstrip("/"), key, backend
        self.work_dir = Path(work_dir).resolve()
        self.client = httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {key}"},
                                   timeout=120, transport=transport, follow_redirects=False,
                                   trust_env=parsed.hostname not in {"localhost", "127.0.0.1", "api", "testserver"})

    def run_once(self):
        # Validate backend before claiming work, so a preview worker cannot consume GPU jobs.
        capability = self.client.get("/v1/capabilities")
        capability.raise_for_status()
        if capability.json()["backend"] != self.backend:
            raise RuntimeError("API and worker backend differ")
        claim = self.client.post("/v1/worker/claim")
        claim.raise_for_status()
        response = claim.json()
        job = response["job"]
        if job is None:
            return False
        job_id, token = job["id"], job["lease_token"]
        directory = self.work_dir / job_id / token
        directory.mkdir(parents=True, exist_ok=True)
        stop = threading.Event()
        lost = threading.Event()

        def renew():
            while not stop.wait(max(1, response["lease_seconds"] / 3)):
                try:
                    result = self.client.post(f"/v1/worker/{job_id}/heartbeat", json={"lease_token": token})
                    result.raise_for_status()
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            image = None
            if job["image_id"]:
                asset = self.client.get(f"/v1/assets/{job['image_id']}")
                asset.raise_for_status()
                image = directory / "input.png"
                image.write_bytes(asset.content)
            output, metadata = generate(self.backend, job, image, directory, lost.is_set)
            if lost.is_set():
                raise RuntimeError("Lease lost before result upload")
            with output.open("rb") as stream:
                upload = self.client.post(f"/v1/worker/{job_id}/complete",
                    data={"lease_token": token, "metadata": json.dumps(metadata)},
                    files={"video": ("video.mp4", stream, "video/mp4")}, timeout=300)
            upload.raise_for_status()
            log.info("Completed %s (%s)", job_id, self.backend)
            if os.environ.get("STAGE_KEEP_WORK", "0") != "1":
                shutil.rmtree(directory)
        except Exception as exc:
            # Detailed errors remain local; public API stores only an error category.
            log.exception("Job %s failed", job_id)
            if not lost.is_set():
                try:
                    self.client.post(f"/v1/worker/{job_id}/fail",
                        json={"lease_token": token, "code": "worker_timeout" if isinstance(exc, TimeoutError) else "inference_failed"}).raise_for_status()
                except Exception:
                    log.error("Could not report failure for %s; lease recovery will handle it", job_id)
        finally:
            stop.set()
            thread.join(timeout=5)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker = Worker(os.getenv("STAGE_API_URL", "http://127.0.0.1:8000"),
                    os.environ.get("STAGE_WORKER_KEY", ""), os.getenv("STAGE_BACKEND", "wan-native"),
                    os.getenv("STAGE_WORK_DIR", "work"))
    try:
        while True:
            try:
                ran = worker.run_once()
                if args.once:
                    break
                if not ran:
                    time.sleep(2)
            except httpx.HTTPError:
                log.exception("API unavailable")
                if args.once:
                    raise
                time.sleep(5)
    finally:
        worker.client.close()


if __name__ == "__main__":
    main()
