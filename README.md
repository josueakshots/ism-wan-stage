# ISM Wan Stage

A runnable draft for image/text-to-video stage generation using the official Wan2.2 TI2V-5B model and Wan VAE. It includes a private web studio, an HTTP API, SQLite job queue, GPU worker, 11 editable A.V./Germani stage presets, and sequential clip continuation.

**Status:** service tests and CPU transport smoke test pass. Real GPU inference remains unverified in this environment. This is a queued video prototype, not a trained LingBot-equivalent or a 3D world generator. Read [MODEL_CARD.md](MODEL_CARD.md) and [TEST_REPORT.md](TEST_REPORT.md).

## Architecture

| Component | Where it runs | Responsibility |
|---|---|---|
| Source and CI | GitHub | Version code, run CPU tests, store test reports |
| API / studio / SQLite / output files | GoDaddy Linux VPS | Receive images/prompts, queue jobs, serve finished videos |
| Native Wan worker | Separate NVIDIA GPU machine, or VPS only if it actually has a suitable GPU | Poll API, load Wan model/VAE, render MP4, upload result |
| Existing game website | Replit/GoDaddy/other host | Its backend calls this API; frontend plays approved clips |

The worker only needs outbound HTTPS to the API. GitHub Actions CPU runners do not perform model generation. A GoDaddy CPU VPS does not become a GPU worker by storing the archive. No ComfyUI account or MCP connection is required by this implementation.

## Quick local service test (no GPU)

Requires Python 3.11+ and `ffmpeg` / `ffprobe` on PATH. Linux deployment is targeted; use WSL for native GPU subprocess execution on Windows.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pip install --no-deps -e .
pytest -q
python scripts/smoke.py --backend preview
```

The smoke test starts a temporary local API, queues a job, runs a CPU worker, uploads/validates an MP4 and downloads it to `work/smoke-result.mp4`. Every frame says **PIPELINE TEST / NOT AI**. It is not a model quality demo.

For the studio, copy `.env.example` to `.env` and generate two different credentials with `python -c "import secrets; print(secrets.token_hex(32))"`. Set `STAGE_BACKEND=preview`, then:

```bash
set -a
. ./.env
set +a
uvicorn stagegen.api:create_app --factory --host 127.0.0.1 --port 8000
```

In a second terminal with the same environment loaded, run `python -m stagegen.worker`. Open `http://127.0.0.1:8000`, enter the private `STAGE_API_KEY`, and generate a test clip. Credentials stay in browser memory for that page, not localStorage.

## Prepare the real GPU worker

On your CUDA NVIDIA Linux host, create two Python environments: a small service environment for this package and a Wan environment for upstream dependencies. Install a CUDA-compatible PyTorch build using the [official PyTorch selector](https://pytorch.org/get-started/locally/). FlashAttention installation requires suitable compiler/CUDA toolkit support; the installer follows upstream requirements. Do not run these heavyweight downloads on the CPU VPS.

Assuming the Wan Python is `/opt/wan-venv/bin/python`, from this project's directory:

```bash
python scripts/install_wan.py --python /opt/wan-venv/bin/python --install-deps
/opt/wan-venv/bin/python scripts/download_model.py
export WAN_PYTHON=/opt/wan-venv/bin/python
export WAN_REPO="$PWD/vendor/Wan2.2"
export WAN_MODEL_DIR="$PWD/models/Wan2.2-TI2V-5B"
python scripts/preflight.py
```

`install_wan.py` pins the source commit and records the resolved GPU environment as `vendor/wan-runtime-lock.txt`. `download_model.py` downloads the complete official snapshot and saves its revision. Large weights are intentionally excluded from Git and this archive. Keep `models/` on persistent GPU storage.

Run both real inference acceptance tests before deploying:

```bash
python scripts/smoke.py --backend wan-native --frames 49 --output work/gpu-text.mp4
python scripts/smoke.py --backend wan-native --frames 49 --image /absolute/path/reference.png --output work/gpu-image.mp4
```

Inspect the videos and JSON reports. Check appearance, motion, frame count, size, seed metadata, and memory/runtime on your GPU. Upstream's 24GB/offload example is a starting point, not a measured resource guarantee for this package. Do not assume 24fps playback means 24 generated frames each second.

## GoDaddy VPS deployment

Use a Linux VPS with Docker Compose, sufficient disk for assets/videos, and a subdomain pointing to its IP. Copy the project, configure `.env` with strong distinct keys and `STAGE_BACKEND=wan-native`, then:

```bash
docker compose up -d --build api
```

The API binds to loopback. Install Caddy and adapt `deploy/Caddyfile` to your domain to serve HTTPS on 80/443. If cPanel/Nginx already handles those ports, add the equivalent HTTPS reverse proxy and 270MB request cap there instead of competing for those ports. Back up the `stage-data` Docker volume and manage retention; automatic deletion is deliberately absent. API data and uploads are single-team data, not tenant-isolated.

On the GPU host, configure `.env.worker` with `STAGE_API_URL=https://your-api-domain`, the same `STAGE_WORKER_KEY`, `STAGE_BACKEND=wan-native`, and absolute `WAN_*` paths. **Do not copy the administrator key to the worker.** Start `python -m stagegen.worker` or adapt `deploy/stage-worker.service`. The sample systemd paths/users must be created to match your installation.

For a Docker-only CPU transport demonstration, set `.env` backend to `preview` and run `docker compose --profile preview up -d --build`. Native CUDA generation uses the external worker setup above; there is no GPU Docker image claimed as tested.

## Generate your game stages

The presets are a proposed starting sequence based on the available A.V./Germani story context. They are editable in `stagegen/presets.json`, not a verified import of every prior script. Your original artwork/video files are not bundled; upload them in the studio.

1. Select a stage or enter a custom prompt.
2. Add a character description and starting image.
3. Choose one action hint and camera composition, then submit.
4. After success, select **Continue from the last completed clip** for another beat. The previous final frame becomes the next starting image.

For a scripted multi-beat sequence, with API and worker already running and `STAGE_API_KEY`/`STAGE_API_URL` set:

```bash
python scripts/render_scenario.py examples/frankfurt-sequence.json --output work/frankfurt
```

This writes MP4s and `playlist.json`. Add `"image":"reference.png"` to a beat to use a local image relative to the scenario JSON. Use `continue_previous` only within the same scene. Each segment is a new generation; continuity is approximate. Scenes can be assembled by your existing video editor/game player; the script does not disguise waiting time as live interaction.

## API contract

Interactive schema: `/docs`. All data endpoints require `Authorization: Bearer ...`.

| Endpoint | Credential | Purpose |
|---|---|---|
| `GET /health` | none | API liveness, not GPU readiness |
| `GET /v1/capabilities` | admin or worker | Backend/settings |
| `GET /v1/stages` | admin | Stage presets |
| `POST /v1/assets` | admin | Multipart `image`; returns image_id |
| `POST /v1/jobs` | admin | JSON matching examples; returns job id |
| `GET /v1/jobs/{id}` | admin | queued/running/succeeded/failed and metadata |
| `GET /v1/jobs/{id}/video` | admin | Validated H.264 MP4 |
| `POST /v1/worker/claim` | worker | Atomically claim one leased job |
| `POST /v1/worker/{id}/heartbeat` | worker | Keep a job lease alive |
| `POST /v1/worker/{id}/complete` | worker | Multipart video + metadata + lease_token |

API has a bounded active queue (20 jobs), two lease attempts, image normalization, frame constraints and stale-worker rejection. Worker errors are recorded as categories; detailed inference logs stay on the GPU host. The service has no arbitrary URL fetching or user-supplied shell commands.

For Only-Memberz / ISMNewWorld, call the API from your existing authenticated **server-side backend** and keep `STAGE_API_KEY` there. Never ship this shared administrator credential in public browser code. Before opening user-paid generation, add your site's per-user authorization, quotas/billing, job ownership, retention, and usage accounting. The included studio is for trusted administrators.

## GitHub handoff

The archive is ready to import into a repository you choose. No repository or live website was modified. GitHub Actions runs the CPU suite and labeled transport preview. Keep weights, `.env`, data, and generated clips out of Git; use the provided `.gitignore`. Do real GPU validation on the worker host, not a standard GitHub-hosted CPU runner.

## Sources

Implementation follows Wan's official `generate.py` argument contract and TI2V config at the pinned commit. The official Wan source and native model are Apache-2.0; this project's original wrapper code is MIT. See [THIRD_PARTY.md](THIRD_PARTY.md).
