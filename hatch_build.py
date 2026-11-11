"""Build hook: a wheel or sdist must contain the built web UI."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class RequireWebUI(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if version == "editable":
            return  # a development install serves whatever is there, or the API alone
        if not Path(self.root, "src", "loracraft", "web_dist", "index.html").is_file():
            raise RuntimeError("The web UI is not built: run `npm install && npm run build` in web/ first.")
