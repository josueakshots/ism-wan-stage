import json
import secrets
import shutil
import uuid
from pathlib import Path
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from .config import Settings
from .media import clean_image, probe_video, extract_last_frame
from .prompts import PRESETS, compose
from .schema import JobRequest, LeaseRequest, FailureRequest, ResultMetadata
from .store import Store


def create_app(settings=None):
    settings = settings or Settings.from_env()
    store = Store(settings)
    root = settings.data_dir
    for folder in ("assets", "outputs"):
        (root / folder).mkdir(exist_ok=True)
    app = FastAPI(title="ISM Wan Stage", version="0.1.0")
    app.state.store = store
    app.state.settings = settings
    security = HTTPBearer(auto_error=False)
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

    def authorize(credentials, key):
        if not credentials or not secrets.compare_digest(credentials.credentials, key):
            raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})

    def admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
        authorize(credentials, settings.api_key)

    def worker(credentials: HTTPAuthorizationCredentials = Depends(security)):
        authorize(credentials, settings.worker_key)

    def either(credentials: HTTPAuthorizationCredentials = Depends(security)):
        if not credentials or not (secrets.compare_digest(credentials.credentials, settings.api_key)
                                   or secrets.compare_digest(credentials.credentials, settings.worker_key)):
            raise HTTPException(401, "Valid bearer token required")

    def job_or_404(job_id):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job

    def public_job(job):
        return {key: value for key, value in job.items() if key not in {"lease_token", "lease_until", "artifact_dir"}}

    def check_lease(job_id, token):
        if not store.owns(job_id, token):
            raise HTTPException(409, "Worker lease expired or superseded")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "ism-wan-stage"}

    @app.get("/v1/capabilities", dependencies=[Depends(either)])
    def capabilities():
        return {"backend": settings.backend, "fps": 24, "max_frames": 121,
                "lease_seconds": settings.lease_seconds, "real_time": False,
                "control": "prompt hints", "continuation": "last decoded frame",
                "weights_loaded": "not checked by API; worker preflight required"}

    @app.get("/v1/stages", dependencies=[Depends(admin)])
    def stages():
        return PRESETS

    @app.post("/v1/assets", dependencies=[Depends(admin)], status_code=201)
    def upload_image(image: UploadFile = File(...)):
        raw = image.file.read(settings.max_upload_bytes + 1)
        if len(raw) > settings.max_upload_bytes:
            raise HTTPException(413, "Image exceeds 10 MiB")
        asset_id = uuid.uuid4().hex
        try:
            clean_image(raw, root / "assets" / f"{asset_id}.png")
        except Exception:
            raise HTTPException(422, "Invalid image: use PNG/JPEG/WebP, 32+ pixels, at most 16 megapixels")
        return {"image_id": asset_id}

    @app.get("/v1/assets/{asset_id}", dependencies=[Depends(either)])
    def get_image(asset_id: str):
        if len(asset_id) != 32 or any(c not in "0123456789abcdef" for c in asset_id):
            raise HTTPException(404)
        path = root / "assets" / f"{asset_id}.png"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/png")

    @app.post("/v1/jobs", dependencies=[Depends(admin)], status_code=202)
    def create_job(request: JobRequest):
        image_id = request.image_id
        if request.parent_job_id:
            parent = job_or_404(request.parent_job_id)
            if parent["state"] != "succeeded":
                raise HTTPException(409, "Parent clip must finish successfully first")
            image_id = uuid.uuid4().hex
            shutil.copyfile(root / parent["artifact_dir"] / "last.png", root / "assets" / f"{image_id}.png")
        if image_id and not (root / "assets" / f"{image_id}.png").is_file():
            raise HTTPException(404, "Image not found")
        try:
            return public_job(store.create(request, compose(request), image_id))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except OverflowError:
            raise HTTPException(429, "Queue is full; try later")

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(admin)])
    def get_job(job_id: str):
        return public_job(job_or_404(job_id))

    @app.get("/v1/jobs/{job_id}/video", dependencies=[Depends(admin)])
    def get_video(job_id: str):
        job = job_or_404(job_id)
        if job["state"] != "succeeded":
            raise HTTPException(409, "Video is not ready")
        return FileResponse(root / job["artifact_dir"] / "video.mp4", media_type="video/mp4",
                            filename=f"{job_id}.mp4")

    @app.post("/v1/worker/claim", dependencies=[Depends(worker)])
    def claim():
        job = store.claim()
        return {"job": job, "backend": settings.backend, "lease_seconds": settings.lease_seconds}

    @app.post("/v1/worker/{job_id}/heartbeat", dependencies=[Depends(worker)])
    def heartbeat(job_id: str, request: LeaseRequest):
        if not store.heartbeat(job_id, request.lease_token):
            raise HTTPException(409, "Worker lease expired or superseded")
        return {"ok": True}

    @app.post("/v1/worker/{job_id}/fail", dependencies=[Depends(worker)])
    def fail(job_id: str, request: FailureRequest):
        if not store.finish(job_id, request.lease_token, error=request.code):
            raise HTTPException(409, "Worker lease expired or superseded")
        return {"ok": True}

    @app.post("/v1/worker/{job_id}/complete", dependencies=[Depends(worker)])
    def complete(job_id: str, lease_token: str = Form(...), metadata: str = Form(...),
                 video: UploadFile = File(...)):
        check_lease(job_id, lease_token)
        job = job_or_404(job_id)
        try:
            meta = ResultMetadata.model_validate_json(metadata)
        except ValueError:
            raise HTTPException(422, "Invalid result metadata")
        if meta.backend != settings.backend or meta.synthetic_preview != (settings.backend == "preview"):
            raise HTTPException(422, "Result backend does not match configured backend")
        if meta.seed != job["request"]["seed"]:
            raise HTTPException(422, "Result seed mismatch")
        # Tokens come from our queue and have already been compared to the stored token.
        attempt_dir = root / "outputs" / job_id / f"{lease_token}-{uuid.uuid4().hex}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            output = attempt_dir / "video.mp4"
            written = 0
            with output.open("wb") as target:
                while chunk := video.file.read(1024 * 1024):
                    written += len(chunk)
                    if written > settings.max_video_bytes:
                        raise HTTPException(413, "Video exceeds upload limit")
                    target.write(chunk)
            actual = probe_video(output)
            expected_size = tuple(map(int, job["request"]["size"].split("*")))
            if (actual["codec"] != "h264" or actual["frames"] != job["request"]["frames"]
                    or abs(actual["fps"] - 24) > 0.1 or actual["seconds"] > 6):
                raise HTTPException(422, "Video does not match requested frame count, codec or fps")
            if settings.backend != "preview" and (actual["width"], actual["height"]) != expected_size:
                raise HTTPException(422, "Video dimensions differ from request")
            extract_last_frame(output, attempt_dir / "last.png")
            result = meta.model_dump()
            result.update({key: actual[key] for key in ("width", "height", "frames", "fps", "seconds")})
            if not store.finish(job_id, lease_token, result=result, artifact_dir=str(attempt_dir.relative_to(root))):
                raise HTTPException(409, "Worker lease expired during upload")
        except HTTPException:
            shutil.rmtree(attempt_dir, ignore_errors=True)
            raise
        except Exception:
            shutil.rmtree(attempt_dir, ignore_errors=True)
            raise HTTPException(422, "Output is not a valid supported video")
        return {"ok": True, "job_id": job_id}

    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(Path(__file__).with_name("static") / "index.html")

    return app
