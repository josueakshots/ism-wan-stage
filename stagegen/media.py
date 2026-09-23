import io
import json
import subprocess
import warnings
from pathlib import Path
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 16_000_000


def clean_image(raw: bytes, destination: Path):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Use a PNG, JPEG or WebP image")
            image.load()
            if min(image.size) < 32:
                raise ValueError("Image must be at least 32 pixels on each side")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2048, 2048))
            image.save(destination, "PNG")


def probe_video(path):
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=codec_name,width,height,nb_read_frames,r_frame_rate:format=duration",
        "-of", "json", str(path)], check=True, capture_output=True, text=True, timeout=60)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    numerator, denominator = map(int, stream["r_frame_rate"].split("/"))
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "frames": int(stream["nb_read_frames"]), "fps": numerator / denominator,
            "seconds": float(data["format"]["duration"]), "codec": stream["codec_name"]}


def extract_last_frame(video, destination):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-1", "-i", str(video),
                    "-update", "1", str(destination)], check=True, capture_output=True, timeout=60)
    if not destination.exists():
        raise ValueError("Video did not yield a last frame")
