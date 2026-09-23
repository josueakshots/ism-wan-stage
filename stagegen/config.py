import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_key: str
    worker_key: str
    backend: str = "wan-native"
    lease_seconds: int = 180
    max_active_jobs: int = 20
    max_attempts: int = 2
    max_upload_bytes: int = 10 * 1024 * 1024
    max_video_bytes: int = 256 * 1024 * 1024
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self):
        if min(len(self.api_key), len(self.worker_key)) < 24 or self.api_key == self.worker_key:
            raise ValueError("Set distinct STAGE_API_KEY and STAGE_WORKER_KEY, each at least 24 characters.")
        if self.backend not in {"wan-native", "preview"}:
            raise ValueError("STAGE_BACKEND must be wan-native or preview.")
        if self.lease_seconds < 15:
            raise ValueError("Lease must be at least 15 seconds.")

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv("STAGE_DATA_DIR", "data")).resolve(),
            api_key=os.environ.get("STAGE_API_KEY", ""),
            worker_key=os.environ.get("STAGE_WORKER_KEY", ""),
            backend=os.getenv("STAGE_BACKEND", "wan-native"),
            lease_seconds=int(os.getenv("STAGE_LEASE_SECONDS", "180")),
            cors_origins=tuple(x.strip() for x in os.getenv("STAGE_CORS_ORIGINS", "").split(",") if x.strip()),
        )
