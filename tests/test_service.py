import io
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from stagegen.api import create_app
from stagegen.config import Settings
from stagegen.schema import JobRequest
from stagegen.backends import generate, native_command
from stagegen.media import probe_video
from stagegen.prompts import compose


@pytest.fixture
def service(tmp_path):
    settings = Settings(data_dir=tmp_path, api_key="admin-" + "a" * 32,
                        worker_key="worker-" + "b" * 32, backend="preview")
    app = create_app(settings)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {settings.api_key}"
    return client, app.state.store, settings


def worker_headers(settings):
    return {"Authorization": f"Bearer {settings.worker_key}"}


def new_job(client, **overrides):
    return client.post("/v1/jobs", json={"prompt": "Germani raises a moonlit ivy shield.", "frames": 17, **overrides})


def test_requires_strong_distinct_keys(tmp_path):
    with pytest.raises(ValueError):
        Settings(tmp_path, "short", "short")


def test_auth_boundaries(service):
    client, _, settings = service
    assert client.get("/health", headers={"Authorization": ""}).status_code == 200
    assert client.get("/v1/stages", headers={"Authorization": ""}).status_code == 401
    assert client.get("/v1/stages", headers=worker_headers(settings)).status_code == 401
    assert client.post("/v1/worker/claim").status_code == 401
    assert client.post("/v1/worker/claim", headers=worker_headers(settings)).status_code == 200


@pytest.mark.parametrize("payload", [
    {"frames": 20}, {"frames": 125}, {"steps": 500}, {"seed": -1},
    {"image_id": "../../etc/passwd"}, {"prompt": ""}, {"size": "832*480"},
    {"action": "arbitrary-shell-command"}, {"extra": "unexpected"},
    {"image_id": "a"*32, "parent_job_id": "b"*32},
])
def test_reject_invalid_request(service, payload):
    client, _, _ = service
    assert new_job(client, **payload).status_code == 422


def test_asset_upload_and_invalid_image(service):
    client, _, _ = service
    assert client.post("/v1/assets", files={"image": ("bad.png", b"not an image")}).status_code == 422
    image = io.BytesIO()
    Image.new("RGB", (64, 64), "green").save(image, "PNG")
    response = client.post("/v1/assets", files={"image": ("../../bad.png", image.getvalue(), "image/png")})
    assert response.status_code == 201
    image_id = response.json()["image_id"]
    assert client.get(f"/v1/assets/{image_id}").status_code == 200
    assert new_job(client, image_id=image_id).status_code == 202
    assert new_job(client, image_id="a" * 32).status_code == 404


def test_prompt_and_missing_preset(service):
    client, _, _ = service
    assert new_job(client, stage_id="unknown").status_code == 422
    job = new_job(client, stage_id="germani-ivy-defense", action="cast").json()
    assert "Germani" in job["prompt"] and "protective spell" in job["prompt"]
    assert "lease_token" not in job


def test_claim_is_atomic(service):
    client, store, _ = service
    job = new_job(client).json()
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: store.claim(), range(8)))
    actual = [claim for claim in claims if claim]
    assert len(actual) == 1 and actual[0]["id"] == job["id"]


def test_expired_worker_cannot_finish_or_heartbeat(service):
    client, store, _ = service
    job = new_job(client).json()
    old = store.claim()
    with store.connection() as db:
        db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time()-5, job["id"]))
    assert not store.heartbeat(job["id"], old["lease_token"])
    fresh = store.claim()
    assert fresh["lease_token"] != old["lease_token"]
    assert not store.finish(job["id"], old["lease_token"], error="stale")
    assert store.heartbeat(job["id"], fresh["lease_token"])
    assert store.finish(job["id"], fresh["lease_token"], error="inference_failed")


def test_expiry_attempt_limit(service):
    client, store, _ = service
    job = new_job(client).json()
    for _ in range(2):
        assert store.claim()
        with store.connection() as db:
            db.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))
    assert store.claim() is None
    assert store.get(job["id"])["state"] == "failed"


def test_queue_limit(service):
    client, _, settings = service
    for _ in range(settings.max_active_jobs):
        assert new_job(client).status_code == 202
    assert new_job(client).status_code == 429


def test_preview_complete_download_and_continuation(service, tmp_path):
    client, store, settings = service
    job = new_job(client).json()
    headers = worker_headers(settings)
    claimed = client.post("/v1/worker/claim", headers=headers).json()["job"]
    output, metadata = generate("preview", claimed, None, tmp_path / "worker")
    actual = probe_video(output)
    assert actual["frames"] == 17 and actual["fps"] == 24
    with output.open("rb") as stream:
        response = client.post(f"/v1/worker/{job['id']}/complete", headers=headers,
            data={"lease_token": claimed["lease_token"], "metadata": json.dumps(metadata)},
            files={"video": ("video.mp4", stream, "video/mp4")})
    assert response.status_code == 200, response.text
    assert client.get(f"/v1/jobs/{job['id']}/video").content[:4] == output.read_bytes()[:4]
    result = client.get(f"/v1/jobs/{job['id']}").json()
    assert result["state"] == "succeeded" and result["result"]["synthetic_preview"] is True
    child = new_job(client, parent_job_id=job["id"]).json()
    assert child["image_id"] and "first frame" in child["prompt"]
    with Image.open(settings.data_dir / "assets" / f"{child['image_id']}.png") as image:
        assert image.size == (384, 216)


def test_cannot_continue_unfinished_job(service):
    client, _, _ = service
    parent = new_job(client).json()
    assert new_job(client, parent_job_id=parent["id"]).status_code == 409


def test_invalid_output_never_publishes(service, tmp_path):
    client, store, settings = service
    job = new_job(client).json()
    claim = store.claim()
    output, metadata = generate("preview", claim, None, tmp_path / "w")
    response = client.post(f"/v1/worker/{job['id']}/complete", headers=worker_headers(settings),
        data={"lease_token": claim["lease_token"], "metadata": json.dumps(metadata)},
        files={"video": ("video.mp4", b"invalid MP4", "video/mp4")})
    assert response.status_code == 422
    assert store.get(job["id"])["state"] == "running"
    assert client.get(f"/v1/jobs/{job['id']}/video").status_code == 409


def test_native_command_matches_upstream_contract():
    request = JobRequest(prompt='Rain; $(touch /tmp/not-executed) " quoted', frames=49)
    job = {"request": request.model_dump(), "prompt": compose(request)}
    cmd = native_command(job, Path("/tmp/a b.png"), Path("/tmp/out.mp4"), Path("/opt/Wan"), Path("/models/Wan"), "/venv/python")
    # Contract checked against upstream generate.py at the locked commit.
    supported = {"--task", "--size", "--ckpt_dir", "--frame_num", "--sample_steps", "--base_seed",
                 "--sample_guide_scale", "--sample_shift", "--offload_model", "--convert_model_dtype",
                 "--t5_cpu", "--save_file", "--prompt", "--image"}
    assert {arg for arg in cmd if arg.startswith("--")} <= supported
    assert cmd[cmd.index("--prompt")+1] == job["prompt"]
    assert cmd[cmd.index("--image")+1] == "/tmp/a b.png"
    assert cmd[cmd.index("--size")+1] == "1280*704"


def test_worker_backend_mismatch_leaves_queue_untouched(service, tmp_path):
    from stagegen.worker import Worker
    client, store, settings = service
    job = new_job(client).json()
    runner = Worker("http://testserver", settings.worker_key, "wan-native", tmp_path)
    runner.client.close()
    runner.client = client
    client.headers["Authorization"] = f"Bearer {settings.worker_key}"
    with pytest.raises(RuntimeError, match="backend differ"):
        runner.run_once()
    assert store.get(job["id"])["state"] == "queued"


def test_worker_failure_records_failed_state(service, tmp_path, monkeypatch):
    from stagegen.worker import Worker
    client, store, settings = service
    job = new_job(client).json()
    runner = Worker("http://testserver", settings.worker_key, "preview", tmp_path)
    runner.client.close()
    runner.client = client
    client.headers["Authorization"] = f"Bearer {settings.worker_key}"
    def fail(*args, **kwargs):
        raise RuntimeError("Injected GPU failure for lifecycle test")
    monkeypatch.setattr("stagegen.worker.generate", fail)
    assert runner.run_once()
    assert store.get(job["id"])["state"] == "failed"
    assert store.get(job["id"])["error"] == "inference_failed"
