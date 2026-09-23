# Third-party references and provenance

Accessed 2026-09-23.

| Resource | Use | License / provenance |
|---|---|---|
| [Wan-Video/Wan2.2](https://github.com/Wan-Video/Wan2.2) | Official inference subprocess installed separately | Apache-2.0; Alibaba Wan Team |
| [Native TI2V-5B checkpoint](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) | Pretrained transformer, Wan VAE, UMT5/tokenizer downloaded by script | Official Wan model license; review snapshot license |
| [Diffusers model card](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers) | API/model research only | Apache-2.0 model card; not the layout used by native backend |
| [HY-World 2.0](https://github.com/Tencent-Hunyuan/HY-World-2.0) | Architectural comparison only | Tencent community license; no code/weights incorporated |
| [LingBot World 2.0](https://github.com/robbyant/lingbot-world-v2) | Architectural comparison only | CC BY-NC-SA 4.0; no code/weights incorporated |

Pinned upstream commit: `1ea34ff48f87168174e12956e200b1d908b1c5ff`.
Reviewed upstream files: `generate.py`, `requirements.txt`, `wan/configs/__init__.py`, `wan/modules/attention.py`, `README.md`, `LICENSE.txt` through the GitHub connection.

No proprietary APIs are needed for this baseline. Existing Python libraries and FFmpeg retain their original licenses. A copy of upstream Wan's Apache license is in `licenses/WAN-APACHE-2.0.txt`; the installer preserves upstream source notices. This wrapper does not grant rights to third-party character artwork or uploaded reference material.
