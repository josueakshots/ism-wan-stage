"""Submit ordered stage beats to an already running API and GPU worker."""
import argparse
import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", help="JSON file with a beats array")
    parser.add_argument("--output", default="work/scenario")
    parser.add_argument("--timeout", type=int, default=7200, help="Maximum wait per clip")
    args = parser.parse_args()
    source = Path(args.scenario).resolve()
    scenario = json.loads(source.read_text())
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    url = os.getenv("STAGE_API_URL", "http://127.0.0.1:8000")
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Remote API must use HTTPS")
    parent = None
    manifest = []
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {os.environ['STAGE_API_KEY']}"},
                      timeout=300, trust_env=parsed.hostname not in {"127.0.0.1", "localhost"}) as client:
        for index, beat in enumerate(scenario["beats"], 1):
            request = dict(beat["request"])
            if beat.get("continue_previous"):
                if not parent:
                    raise ValueError("First beat cannot continue a previous clip")
                if beat.get("image"):
                    raise ValueError("A beat cannot both continue and supply a new image")
                request["parent_job_id"] = parent
            elif beat.get("image"):
                with (source.parent / beat["image"]).open("rb") as image:
                    response = client.post("/v1/assets", files={"image": image})
                    response.raise_for_status()
                    request["image_id"] = response.json()["image_id"]
            response = client.post("/v1/jobs", json=request)
            response.raise_for_status()
            job = response.json()
            print(f"Beat {index}: queued {job['id']}", flush=True)
            deadline = time.monotonic() + args.timeout
            while job["state"] in {"queued", "running"}:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Still waiting for {job['id']}; the server job is not canceled")
                time.sleep(2)
                response = client.get(f"/v1/jobs/{job['id']}")
                response.raise_for_status()
                job = response.json()
            if job["state"] != "succeeded":
                raise RuntimeError(f"Beat {index} failed: {job['error']}")
            path = output / f"beat-{index:02d}.mp4"
            response = client.get(f"/v1/jobs/{job['id']}/video")
            response.raise_for_status()
            path.write_bytes(response.content)
            manifest.append({"file": path.name, "job_id": job["id"], "request": request, "result": job["result"]})
            (output / "playlist.json").write_text(json.dumps(manifest, indent=2))
            parent = job["id"]
            print(f"Beat {index}: saved {path.name}", flush=True)


if __name__ == "__main__":
    main()
