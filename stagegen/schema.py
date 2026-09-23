from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = str


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=3000)
    character: str = Field(default="", max_length=700)
    stage_id: str | None = Field(default=None, max_length=80)
    image_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    parent_job_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    action: Literal["observe", "walk", "run", "dodge", "cast", "jump", "drive"] = "observe"
    camera: Literal["follow", "fixed", "orbit", "wide"] = "follow"
    size: Literal["1280*704", "704*1280"] = "1280*704"
    frames: int = Field(default=81, ge=17, le=121)
    steps: int = Field(default=30, ge=5, le=50)
    seed: int = Field(default=42, ge=0, le=2147483647)

    @model_validator(mode="after")
    def validate_inputs(self):
        if self.frames % 4 != 1:
            raise ValueError("Wan frame counts must equal 4n+1, for example 49, 81, or 121.")
        if self.image_id and self.parent_job_id:
            raise ValueError("Choose an image or a parent clip, not both.")
        return self


class LeaseRequest(BaseModel):
    lease_token: str = Field(pattern=r"^[a-f0-9]{32}$")


class FailureRequest(LeaseRequest):
    code: Literal["inference_failed", "worker_timeout", "upload_failed", "invalid_output"]


class ResultMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["wan-native", "preview"]
    synthetic_preview: bool
    model_id: str = Field(max_length=150)
    model_revision: str = Field(max_length=100)
    upstream_revision: str = Field(max_length=100)
    seed: int
    fps: int = Field(ge=1, le=60)
    frames: int = Field(ge=1, le=121)
    width: int = Field(ge=16, le=4096)
    height: int = Field(ge=16, le=4096)
    seconds: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
