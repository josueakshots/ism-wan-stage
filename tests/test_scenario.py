"""Runs the actual CLI client, HTTP server and polling worker across three clips."""
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx


def test_three_beat_scenario(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "STAGE_API_KEY": secrets.token_hex(24), "STAGE_WORKER_KEY": secrets.token_hex(24),
           "STAGE_BACKEND": "preview", "STAGE_DATA_DIR": str(tmp_path / "data"),
           "STAGE_WORK_DIR": str(tmp_path / "worker"), "STAGE_API_URL": url}
    processes = []
    try:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "stagegen.api:create_app", "--factory",
                                "--host", "127.0.0.1", "--port", str(port)], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(api)
        with httpx.Client(base_url=url, trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(.1)
            else:
                raise AssertionError("API did not start")
        worker = subprocess.Popen([sys.executable, "-m", "stagegen.worker"], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(worker)
        output = tmp_path / "sequence"
        result = subprocess.run([sys.executable, "scripts/render_scenario.py", "examples/frankfurt-sequence.json",
                                 "--output", str(output), "--timeout", "30"], env=env,
                                 capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        manifest = json.loads((output / "playlist.json").read_text())
        assert len(manifest) == 3
        assert all(item["result"]["synthetic_preview"] for item in manifest)
        assert all((output / item["file"]).stat().st_size > 1000 for item in manifest)
        assert manifest[1]["request"]["parent_job_id"] == manifest[0]["job_id"]
        assert manifest[2]["request"]["parent_job_id"] == manifest[1]["job_id"]
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
