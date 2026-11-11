"""Structured progress events: one JSON object per line, on stdout and in events.jsonl."""

import json
import sys
import time
from pathlib import Path


class EventSink:
    def __init__(self, run_dir: Path):
        self._file = open(run_dir / "events.jsonl", "a", encoding="utf-8")

    def emit(self, type: str, **data) -> None:
        line = json.dumps({"type": type, "time": time.time(), **data}, ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def close(self) -> None:
        self._file.close()
