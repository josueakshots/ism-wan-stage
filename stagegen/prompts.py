import json
from pathlib import Path

PRESETS = json.loads(Path(__file__).with_name("presets.json").read_text())
STAGES = {s["id"]: s for s in PRESETS}
ACTIONS = {
    "observe": "The character pauses, observing the surroundings with subtle natural movement.",
    "walk": "The character walks steadily forward through the scene.",
    "run": "The character runs forward with clear, continuous body movement.",
    "dodge": "The character makes one controlled sideways dodge and regains balance.",
    "cast": "The character casts one luminous protective spell with a clear hand gesture.",
    "jump": "The character makes one short leap and lands securely.",
    "drive": "The character drives forward slowly, keeping clear of obstacles.",
}
CAMERAS = {
    "follow": "Smooth third-person camera follows behind the character.",
    "fixed": "Locked camera, stable framing, no cuts.",
    "orbit": "Camera makes a slow short orbit around the character.",
    "wide": "Wide establishing composition with restrained camera movement.",
}


def compose(request):
    stage = STAGES.get(request.stage_id)
    if request.stage_id and not stage:
        raise ValueError("Unknown stage_id")
    parts = ["Cinematic fantasy game scene, one continuous shot."]
    if stage:
        parts.extend([stage["scene"], "Current objective: " + stage["objective"] + "."])
    if request.character:
        parts.append("Character appearance: " + request.character)
    parts.extend([request.prompt, ACTIONS[request.action], CAMERAS[request.camera]])
    if request.image_id or request.parent_job_id:
        parts.append("Preserve the supplied first frame's character appearance, outfit, lighting and setting.")
    return " ".join(parts)
