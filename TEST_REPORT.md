# Validation report

Prepared 2026-09-23. This report separates service verification from model inference.

## Completed

| Check | Result |
|---|---|
| Automated suite, Python 3.12 | 25 passed in 7.58 seconds; JUnit evidence in `validation/pytest.xml` |
| Full HTTP synthetic-video smoke test | API started, job queued, worker rendered and uploaded, server validated, client downloaded MP4 |
| Smoke media inspection | H.264, 49 frames, 384x216, 24fps, 2.041667 seconds; visibly labeled PIPELINE TEST / NOT AI |
| Three-beat scenario integration | Real API and worker processes; CLI downloaded three clips, wrote playlist, and continued using previous final frames |
| Queue and access checks | Credential role separation, invalid inputs, queue limits, atomic claims, lease expiry/retries, worker mismatch, invalid output rejection |
| Packaging checks | Editable Python install, Python compilation, JavaScript syntax, JSON and YAML parsing passed |
| Upstream command contract | Reviewed official Wan `generate.py` at pinned commit `1ea34ff48f87168174e12956e200b1d908b1c5ff` |

The suite emitted one non-fatal Starlette/AnyIO TestClient deprecation warning. An environment proxy issue found during the HTTP smoke test was fixed by disabling inherited proxy configuration for local worker connections. Remote connections retain environment proxy support.

`requirements-lock.txt` records the resolved CPU test environment. GPU dependencies are installed separately from pinned upstream code and recorded by the installer.

## Not verified

- No CUDA GPU, PyTorch installation, or model checkpoint was available here. Neither text-to-video nor image-to-video native Wan inference was executed.
- No new weights or learned action controller were trained. Synthetic test videos demonstrate the transport pipeline only.
- Docker image build, GPU installation, browser visual review, and GoDaddy deployment were not executed.
- No repository was created or changed, and no production service was deployed.
- Visual continuity, character fidelity, action adherence, GPU memory, and rendering speed remain unmeasured.

Preflight correctly reported missing CUDA, upstream checkout, model revision lock, and VAE checkpoint in this environment. Its failure is expected and must be resolved on the GPU host.

## GPU acceptance gate

Follow the README installation steps on the target NVIDIA Linux host, then run:

```bash
python scripts/preflight.py
python scripts/smoke.py --backend wan-native --frames 49 --output work/gpu-text.mp4
python scripts/smoke.py --backend wan-native --frames 49 --image /absolute/path/reference.png --output work/gpu-image.mp4
```

Both real inference tests must succeed, with output videos and metadata inspected, before treating the generator as deployment-ready. Then exercise a short scenario against the actual HTTPS API and verify clip quality and worker restart behavior. This draft supports queued stage clips; it does not provide real-time LingBot-style control or HY-World-style 3D reconstruction.
