import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageOps
from .media import probe_video

MODEL_ID = "Wan-AI/Wan2.2-TI2V-5B"
UPSTREAM_REVISION = "1ea34ff48f87168174e12956e200b1d908b1c5ff"


def native_command(job, image, output, repo, weights, python):
    request = job["request"]
    command = [str(python), str(Path(repo) / "generate.py"), "--task", "ti2v-5B",
               "--size", request["size"], "--ckpt_dir", str(weights), "--frame_num", str(request["frames"]),
               "--sample_steps", str(request["steps"]), "--base_seed", str(request["seed"]),
               "--sample_guide_scale", "5.0", "--sample_shift", "5.0", "--offload_model", "True",
               "--convert_model_dtype", "--t5_cpu", "--save_file", str(output), "--prompt", job["prompt"]]
    if image:
        command.extend(["--image", str(image)])
    return command


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run_native(job, image, directory, should_abort):
    repo = Path(os.environ.get("WAN_REPO", "vendor/Wan2.2")).resolve()
    weights = Path(os.environ.get("WAN_MODEL_DIR", "models/Wan2.2-TI2V-5B")).resolve()
    python = os.environ.get("WAN_PYTHON", sys.executable)
    if not (repo / "generate.py").is_file():
        raise RuntimeError("Install the pinned Wan repository before starting this worker")
    lock_path = weights / "stage-model-lock.json"
    if not lock_path.exists():
        raise RuntimeError("Download weights with scripts/download_model.py first")
    lock = json.loads(lock_path.read_text())
    if lock["model_id"] != MODEL_ID:
        raise RuntimeError("Incorrect model checkpoint")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if revision != UPSTREAM_REVISION:
        raise RuntimeError("Wan checkout differs from the validated command contract")
    output = directory / "video.mp4"
    fitted = None
    if image:
        fitted = directory / "input-fitted.png"
        size = tuple(map(int, job["request"]["size"].split("*")))
        with Image.open(image) as source:
            ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS).save(fitted)
    command = native_command(job, fitted, output, repo, weights, python)
    timeout = int(os.environ.get("WAN_JOB_TIMEOUT_SECONDS", "3600"))
    started = time.monotonic()
    with (directory / "inference.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                if should_abort():
                    raise RuntimeError("Worker lease lost")
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Wan inference timeout")
                time.sleep(0.5)
            if process.returncode:
                raise RuntimeError("Wan inference failed; inspect the local inference.log")
        finally:
            stop_process(process)
    return output, {"model_id": MODEL_ID, "model_revision": lock["revision"], "upstream_revision": revision}


def run_preview(job, image, directory, should_abort):
    """Synthetic transport test only. No weights, AI motion, or claimed generation."""
    output = directory / "video.mp4"
    width, height = (384, 216) if job["request"]["size"].startswith("1280") else (216, 384)
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
               f"{width}x{height}", "-r", "24", "-i", "-", "-an", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    with (directory / "preview.log").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for i in range(job["request"]["frames"]):
                if should_abort():
                    raise RuntimeError("Worker lease lost")
                frame = Image.new("RGB", (width, height), (12, 21, 35))
                draw = ImageDraw.Draw(frame)
                draw.rectangle((12, 12, width - 12, height - 12), outline=(40, 170, 120), width=2)
                draw.text((24, 35), "PIPELINE TEST / NOT AI", fill="white")
                draw.text((24, 70), "No model weights used", fill=(150, 200, 180))
                draw.text((24, 105), f"Frame {i + 1} / {job['request']['frames']}", fill="white")
                draw.rectangle((24, height - 42, 24 + int((width - 48) * (i + 1) / job["request"]["frames"]), height - 30), fill=(40, 170, 120))
                process.stdin.write(frame.tobytes())
            process.stdin.close()
            if process.wait(timeout=60):
                raise RuntimeError("Preview encoder failed")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    return output, {"model_id": "none-synthetic-test", "model_revision": "none", "upstream_revision": "none"}


def generate(backend, job, image, directory, should_abort=lambda: False):
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    output, provenance = (run_preview if backend == "preview" else run_native)(job, image, directory, should_abort)
    actual = probe_video(output)
    metadata = {"backend": backend, "synthetic_preview": backend == "preview", **provenance,
                "seed": job["request"]["seed"], "fps": round(actual["fps"]), "frames": actual["frames"],
                "width": actual["width"], "height": actual["height"], "seconds": actual["seconds"],
                "elapsed_seconds": round(time.monotonic() - started, 3)}
    (directory / "result.json").write_text(json.dumps(metadata, indent=2))
    return output, metadata
