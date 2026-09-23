"""Download the real pretrained model, VAE, tokenizer and T5. Run on GPU host."""
import argparse
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument("--directory", default="models/Wan2.2-TI2V-5B")
parser.add_argument("--revision", default="main", help="Use a saved commit revision to reproduce a previous download")
args = parser.parse_args()
model_id = "Wan-AI/Wan2.2-TI2V-5B"
revision = HfApi().model_info(model_id, revision=args.revision).sha
directory = Path(args.directory).resolve()
snapshot_download(repo_id=model_id, revision=revision, local_dir=directory)
required = ["Wan2.2_VAE.pth", "models_t5_umt5-xxl-enc-bf16.pth", "config.json"]
for name in required:
    if not (directory / name).is_file():
        raise SystemExit(f"Missing checkpoint component: {name}")
(directory / "stage-model-lock.json").write_text(json.dumps({"model_id": model_id, "revision": revision}, indent=2))
print(f"Downloaded full checkpoint to {directory}; revision {revision}")
