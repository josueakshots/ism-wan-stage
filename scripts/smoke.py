"""Full HTTP API + worker test. --backend wan-native is the real GPU acceptance test."""
import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import httpx
from stagegen.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["preview", "wan-native"], default="preview")
    parser.add_argument("--image", help="Optional reference image for real image-to-video acceptance")
    parser.add_argument("--output", default="work/smoke-result.mp4")
    parser.add_argument("--frames", type=int, default=17)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="stage-smoke-") as temporary:
        admin, worker_key = secrets.token_hex(24), secrets.token_hex(24)
        env = {**os.environ, "STAGE_API_KEY": admin, "STAGE_WORKER_KEY": worker_key,
               "STAGE_DATA_DIR": temporary, "STAGE_BACKEND": args.backend}
        url = f"http://127.0.0.1:{port}"
        client = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {admin}"}, timeout=120, trust_env=False)
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "stagegen.api:create_app", "--factory",
                                    "--host", "127.0.0.1", "--port", str(port)], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        runner = None
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(.1)
            else:
                raise RuntimeError("API did not start")
            image_id = None
            if args.image:
                with open(args.image, "rb") as image:
                    response = client.post("/v1/assets", files={"image": image})
                    response.raise_for_status()
                    image_id = response.json()["image_id"]
            response = client.post("/v1/jobs", json={"prompt": "A moonlit ivy barrier grows across a rainy Frankfurt alley.",
                "stage_id": "germani-ivy-defense", "frames": args.frames, "steps": 30, "image_id": image_id})
            response.raise_for_status()
            job = response.json()
            runner = Worker(url, worker_key, args.backend, Path(temporary) / "worker")
            assert runner.run_once(), "Worker did not claim the job"
            result = client.get(f"/v1/jobs/{job['id']}").json()
            if result["state"] != "succeeded":
                raise RuntimeError(f"Smoke test failed: {result}")
            output = Path(args.output).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            response = client.get(f"/v1/jobs/{job['id']}/video")
            response.raise_for_status()
            output.write_bytes(response.content)
            report = {"test": "full-http-worker-smoke", "passed": True,
                      "inference_tested": args.backend == "wan-native", "result": result["result"], "output": str(output)}
            output.with_suffix(".json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
        finally:
            client.close()
            if runner:
                runner.client.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
