# ISM Wan Stage 0.1 — model configuration

This deliverable is an application around existing pretrained weights. No new foundation model, action adapter, LoRA, distillation checkpoint, or world-reconstruction model was trained in this task.

## Pretrained components

- Repository: `Wan-AI/Wan2.2-TI2V-5B` on Hugging Face (native checkpoint layout).
- Native inference source: `Wan-Video/Wan2.2`, commit `1ea34ff48f87168174e12956e200b1d908b1c5ff`.
- Wan2.2 VAE: `Wan2.2_VAE.pth`; the official pipeline loads it automatically.
- Denoiser: pretrained 5B TI2V transformer; use all shard files from the model snapshot.
- Text conditioning: UMT5 encoder and tokenizer from that snapshot.
- Model revision: resolved once by `scripts/download_model.py`, then recorded in `stage-model-lock.json` and every successful result. Supply `--revision COMMIT` to reproduce a download.
- Default native generation: 1280×704, 81 frames, 24 fps, 30 sampling steps, guidance 5, shift 5, CPU model offload and T5 on CPU. Native also supports 704×1280.

The archive contains no large weights. The downloader retrieves the full snapshot, including dependencies such as the VAE and text encoder, directly from the official model repository. A VAE alone cannot generate prompted scenes.

## Behavior and limitations

Text input produces a clip; a supplied image anchors its first frame. Continuation decodes a prior MP4's final frame and feeds that image into a new generation. This carries appearance context, not persistent latent memory, action history, camera geometry, or physical state. Drift and discontinuities are expected.

Action and camera choices are English prompt hints. They are not learned control channels. There is no keyboard-to-frame real-time loop, simulation engine, collision system, health/inventory state, 3D mesh generation, or dependable character identity. Keep real game state in the game engine. No audio generation is implemented.

The browser displays encoded output at 24 fps; this is playback rate, NOT inference throughput. Native model loading happens per job in this version. Subprocess isolation simplifies crash recovery but adds latency. Clips are limited to 121 frames (~5 seconds). Longer scenes use separately generated beats.

## Hardware and evaluation

Upstream documents a 24GB GPU path for TI2V-5B with CPU offloading and T5 on CPU. This is not a tested memory guarantee for this wrapper. Plan a CUDA NVIDIA worker with enough system RAM and disk for the full snapshot, temporary files, and offloaded components. Benchmark the actual GPU with `scripts/preflight.py` and the two GPU smoke tests in README before committing to a hosting plan or concurrency target.

This task validated only service behavior and synthetic CPU video transport. Native CUDA inference, peak VRAM, seconds per clip, reference fidelity, and Docker deployment have NOT been measured here. See TEST_REPORT.md.

## Path toward an interactive world model

1. Collect rights-cleared gameplay trajectories, aligned frame/action/camera timestamps, stage descriptions, and character references; keep held-out scenes and characters for evaluation.
2. Add action/camera conditioning to the Wan transformer and train the added parameters against video-latent targets encoded by the Wan VAE. Merely converting keypresses into text prompts does not perform this training.
3. Train temporal memory/causal rollouts and evaluate action compliance, long-horizon drift, repeat-visit consistency, and recovery after occlusion.
4. Distill for few-step inference, implement a persistent GPU session server, and benchmark end-to-end latency including capture, model inference, encoding, and network streaming.

Those training/serving stages are future work, not implemented modules or released weights in this package. HY-World's 3D reconstruction is an additional pipeline and is not implemented here.

## Source and license references

- https://github.com/Wan-Video/Wan2.2
- https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- https://github.com/Wan-Video/Wan2.2/blob/main/LICENSE.txt
- https://github.com/robbyant/lingbot-world-v2 (comparison only; no code or weights bundled)
- https://github.com/Tencent-Hunyuan/HY-World-2.0 (comparison only; no code or weights bundled)

Wan's official repository/model describe Apache-2.0 licensing. This wrapper uses MIT; dependencies retain their own licenses. LingBot/HY-World code and weights are excluded from this implementation.
