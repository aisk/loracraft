# LoraCraft

A LoRA training workbench: manage datasets, captions, training runs and results in one place.
SDXL first.

## What it does

- **Dataset**: import images with their captions, browse and filter by tag, edit tags one image at a
  time or in bulk, spot missing captions and undersized images.
- **Auto-captioning**: a vision LLM (any OpenAI-compatible endpoint, local or hosted) writes captions
  according to what the LoRA is for: a character, a style or a concept. Results are suggestions you
  accept or discard; with a tag dictionary installed, invented tags are flagged or corrected.
- **Training**: a self-contained SDXL LoRA trainer with plain-language setup, a queue, live progress
  and preview images after every round.
- **Results**: preview images of every round side by side, pick the best round, export it.

## Layout

```
src/loracraft/
  server/        FastAPI backend: projects, dataset, auto-captioning, run queue
  trainer/       SDXL LoRA trainer, runs as its own process
  vendor/kohya/  code adapted from kohya-ss/sd-scripts (Apache-2.0)
web/             Svelte frontend
tests/
```

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Node.js.

```sh
uv sync                              # Python environment, including PyTorch
cd web && npm install && npm run build
```

`pyproject.toml` currently pins PyTorch to the AMD ROCm build for Windows and RDNA2 cards
(`device-gfx1030`). For another AMD card, change the `device-gfx…` names; other GPU vendors are not
wired up yet.

## Run

```sh
uv run loracraft                     # http://127.0.0.1:8600
```

User data (database, images, runs) lives in `./workspace`; set `LORACRAFT_HOME` to move it.

For frontend development, run `npm run dev` in `web/` alongside the server and open
http://localhost:5600.

## Training worker

A run is a directory containing `config.json` (see `trainer/config.py`):

```sh
uv run python -m loracraft.trainer <run_dir>
```

It writes `events.jsonl`, `checkpoints/` and `samples/` into the same directory. Create a file
named `stop` there to stop gracefully. Checkpoints use kohya's key names and metadata, so they load
in ComfyUI and WebUI.

## Tag dictionary

To validate Danbooru tags written by the vision model, put a tag list such as `danbooru.csv` (first
column: tag name) into `<workspace>/dictionaries/`. Without one, validation is skipped.

## Tests

```sh
uv run pytest
```

## Third-party code

`src/loracraft/vendor/kohya/` contains modified code from
[kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts), licensed under Apache-2.0. See the
README in that directory for the source commit and the list of changes.
