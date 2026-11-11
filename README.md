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

## Install

Requires Python 3.12. Training needs a GPU that PyTorch drives through CUDA or ROCm; the dataset
and captioning tools work without one.

Apple Silicon (MPS) is wired up but **has never been run on a Mac**: expect it to need fixes. It
trains in full precision only, so it wants a lot of memory. On a Mac, plain `pip install loracraft`
is enough, since the PyTorch build on PyPI includes MPS.

Install PyTorch **first**, from the index that matches your GPU, then LoraCraft. Which index that is
(CUDA version, ROCm, …) is listed at [pytorch.org](https://pytorch.org/get-started/locally/):

```sh
python -m venv .venv                 # then activate it
pip install torch --index-url <index for your GPU>
pip install loracraft
```

The order matters. LoraCraft accepts any PyTorch build, so the one you installed is kept; without
one, `pip install loracraft` brings the default build from PyPI, which on Windows cannot use the
GPU. If that happened, repeat the `pip install torch …` line with `--force-reinstall`. The training
page tells you when the installed PyTorch cannot train.

## Run

```sh
loracraft                            # http://127.0.0.1:8600
python -m loracraft --port 8700      # the same, on another port
```

User data (database, images, runs) lives in the per-user data directory, printed at startup:
`%LOCALAPPDATA%\loracraft` on Windows, `~/Library/Application Support/loracraft` on macOS,
`~/.local/share/loracraft` on Linux. Set `LORACRAFT_HOME` to keep it elsewhere.

## Development

Requires [uv](https://docs.astral.sh/uv/) and Node.js.

```sh
uv sync                              # Python environment, including PyTorch
cd web && npm install && npm run build
uv run loracraft
```

`uv sync` installs the `torch-rocm` dependency group, which pins PyTorch to the AMD ROCm build for
Windows and RDNA2 cards (`device-gfx1030`). For another AMD card, change the `device-gfx…` names;
for another vendor, replace the group.

`npm run build` writes the web UI into `src/loracraft/web_dist/`, from where the server serves it.
For frontend work, run `npm run dev` in `web/` alongside the server and open http://localhost:5600.

To build the distributions (the web UI must be built first):

```sh
uv build
```

## Training worker

A run is a directory containing `config.json` (see `trainer/config.py`):

```sh
python -m loracraft.trainer <run_dir>
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
