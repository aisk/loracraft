"""Entry point of the training worker process: `python -m loracraft.trainer <run_dir>`."""

import sys
from pathlib import Path

from .loop import run


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m loracraft.trainer <run_dir>")
    run(Path(sys.argv[1]))


if __name__ == "__main__":
    main()
