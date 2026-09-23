"""Fail clearly on absent GPU/software/weights instead of silently using a fake backend."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

checks = {}
for command in ("ffmpeg", "ffprobe", "git"):
    checks[command] = bool(shutil.which(command))
repo = Path(os.getenv("WAN_REPO", "vendor/Wan2.2"))
model = Path(os.getenv("WAN_MODEL_DIR", "models/Wan2.2-TI2V-5B"))
checks["upstream_code"] = (repo / "generate.py").is_file()
checks["model_lock"] = (model / "stage-model-lock.json").is_file()
checks["wan_vae"] = (model / "Wan2.2_VAE.pth").is_file()
python = os.getenv("WAN_PYTHON", sys.executable)
script = "import torch,json; print(json.dumps({'cuda':torch.cuda.is_available(),'gpus':[{'name':torch.cuda.get_device_name(i),'vram_gib':round(torch.cuda.get_device_properties(i).total_memory/2**30,1)} for i in range(torch.cuda.device_count())]}))"
try:
    result = subprocess.run([python, "-c", script], text=True, capture_output=True, check=True, timeout=30)
    gpu = json.loads(result.stdout)
    checks["cuda"] = gpu["cuda"]
except Exception:
    gpu = {"error": "PyTorch/CUDA unavailable in WAN_PYTHON"}
    checks["cuda"] = False
print(json.dumps({"checks": checks, "gpu": gpu, "status": "ready-for-smoke-test" if all(checks.values()) else "blocked"}, indent=2))
sys.exit(0 if all(checks.values()) else 1)
