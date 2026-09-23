"""Prepare official upstream source and GPU dependencies in an existing CUDA Python environment."""
import argparse
import subprocess
import sys
from pathlib import Path

REVISION = "1ea34ff48f87168174e12956e200b1d908b1c5ff"
parser = argparse.ArgumentParser()
parser.add_argument("--directory", default="vendor/Wan2.2")
parser.add_argument("--python", default=sys.executable)
parser.add_argument("--install-deps", action="store_true")
args = parser.parse_args()
directory = Path(args.directory).resolve()
if directory.exists():
    current = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"], text=True).strip()
    if current != REVISION:
        raise SystemExit("Existing checkout differs. Choose an empty directory; no files were changed.")
else:
    directory.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--no-checkout", "https://github.com/Wan-Video/Wan2.2.git", str(directory)], check=True)
    subprocess.run(["git", "-C", str(directory), "checkout", REVISION], check=True)
if args.install_deps:
    subprocess.run([args.python, "-c", "import torch; assert torch.cuda.is_available(), 'A CUDA-enabled PyTorch environment is required'"], check=True)
    requirements = (directory / "requirements.txt").read_text().splitlines()
    # FlashAttention needs torch and build prerequisites installed first.
    base = directory.parent / "wan-base-requirements.txt"
    base.write_text("\n".join(line for line in requirements if not line.strip().startswith("flash_attn")) + "\n")
    subprocess.run([args.python, "-m", "pip", "install", "packaging", "ninja", "wheel", "setuptools"], check=True)
    subprocess.run([args.python, "-m", "pip", "install", "-r", str(base)], check=True)
    subprocess.run([args.python, "-m", "pip", "install", "flash-attn", "--no-build-isolation"], check=True)
    frozen = subprocess.check_output([args.python, "-m", "pip", "freeze"], text=True)
    (directory.parent / "wan-runtime-lock.txt").write_text(frozen)
print(f"Wan source ready at {directory}, commit {REVISION}")
