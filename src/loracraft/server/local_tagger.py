"""Tagging on this machine with a WD tagger: an image classifier over Danbooru tags, not an LLM.

It needs no setup and no GPU, and only ever writes real tags, but it cannot be given instructions:
it tags what it sees, and the profile's rules are applied to the result afterwards.

Runs on ONNX Runtime rather than PyTorch, so it does not depend on which PyTorch build is installed
and does not compete with a training run for the GPU.
"""

import csv
import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from ..imaging import to_rgb

# Hugging Face repositories offered in the UI, most accurate first, with their download size in GB.
# Any repository with the same layout (model.onnx and selected_tags.csv) works.
MODELS = {
    "SmilingWolf/wd-eva02-large-tagger-v3": 1.3,
    "SmilingWolf/wd-swinv2-tagger-v3": 0.5,
    "SmilingWolf/wd-vit-tagger-v3": 0.4,
}
DEFAULT_MODEL = next(iter(MODELS))

# Categories in selected_tags.csv
GENERAL, CHARACTER = 0, 4
# Naming a character wrongly does more harm than missing one, so those tags need more confidence.
CHARACTER_THRESHOLD = 0.85

# GPU providers are used when the installed ONNX Runtime build has them; the default build is CPU-only.
PROVIDERS = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]


def read_labels(path: Path) -> list[tuple[str, int]]:
    """(tag, category) for each output of the model, in order."""
    with open(path, encoding="utf-8", newline="") as f:
        return [(row["name"], int(row["category"])) for row in csv.DictReader(f)]


def select_tags(scores, labels: list[tuple[str, int]], threshold: float) -> dict[str, list[str]]:
    """The tags scoring above their threshold, most confident first. Rating tags are left out."""
    found: dict[str, list[str]] = {"general": [], "character": []}
    for index in sorted(range(len(labels)), key=lambda i: -scores[i]):
        name, category = labels[index]
        if category == GENERAL and scores[index] >= threshold:
            found["general"].append(name)
        elif category == CHARACTER and scores[index] >= CHARACTER_THRESHOLD:
            found["character"].append(name)
    return found


class Tagger:
    def __init__(self, repo: str, on_download: Callable[[float], None] | None = None):
        """Load the model, downloading it on first use. `on_download` receives progress from 0 to 1."""
        import onnxruntime  # slow to import, and only needed here
        from huggingface_hub import hf_hub_download
        from tqdm import tqdm

        class Progress(tqdm):
            def update(self, n=1):
                super().update(n)
                if on_download and self.total:
                    on_download(self.n / self.total)

        self.labels = read_labels(Path(hf_hub_download(repo, "selected_tags.csv")))
        model = hf_hub_download(repo, "model.onnx", tqdm_class=Progress)
        available = onnxruntime.get_available_providers()
        self.session = onnxruntime.InferenceSession(model, providers=[p for p in PROVIDERS if p in available])
        self.input = self.session.get_inputs()[0]
        self.size = self.input.shape[1]  # NHWC, square

    def tag(self, path: Path, threshold: float) -> dict[str, list[str]]:
        with Image.open(path) as image:
            image = to_rgb(image)
            # The models were trained on images padded to a square with white, in BGR, valued 0-255.
            side = max(image.size)
            square = Image.new("RGB", (side, side), (255, 255, 255))
            square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
        square = square.resize((self.size, self.size), Image.BICUBIC)
        pixels = np.asarray(square, dtype=np.float32)[:, :, ::-1]
        scores = self.session.run(None, {self.input.name: np.ascontiguousarray(pixels)[None]})[0][0]
        return select_tags(scores, self.labels, threshold)


# --- Tags that describe who a character is -----------------------------------

COLOURS = (
    "aqua|black|blue|brown|green|grey|orange|pink|purple|red|white|yellow|amber|silver|golden|multicolored|"
    "two-tone|gradient"
)
IDENTITY = re.compile(
    rf"(.+ hair|.*bangs|(?:{COLOURS}) eyes|ahoge|sidelocks|hair between eyes|hair intakes|hair over one eye|"
    r"heterochromia|(?:\w+ )?breasts|flat chest|dark skin|dark-skinned (?:fe)?male)"
)


def is_identity_tag(tag: str) -> bool:
    """Whether a (normalized) tag describes hair or eye colour, the cut of the hair, or the body.

    These belong to a character rather than to one picture of them. Hairstyles that are put up and
    taken down (ponytail, braid...) and states of the eyes (closed eyes...) are not included.
    """
    return IDENTITY.fullmatch(tag) is not None
