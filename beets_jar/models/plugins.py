"""Side-panel plugins, as read from plugin_manifest.yaml and the plugins' own parsers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

Target = Literal["album", "item", "flag"]


@dataclass(frozen=True)
class PluginOption:
    dest: str
    type: str  # bool | int | float | string
    default: Any  # what the command uses if the user changes nothing
    help: str | None = None

    @property
    def ui_default(self) -> Any:
        """The default as the settings box shows it. Bools stay bools; the rest
        become strings so they compare cleanly with <input> values in the browser."""
        if self.type == "bool":
            return bool(self.default)
        return "" if self.default is None else str(self.default)


@dataclass(frozen=True)
class PluginCommand:
    name: str
    target: Target
    options: tuple[PluginOption, ...] = ()
    fixed: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PanelPlugin:
    name: str
    commands: tuple[PluginCommand, ...]

    def command(self, name: str) -> PluginCommand | None:
        return next((c for c in self.commands if c.name == name), None)

    @property
    def ui_defaults(self) -> dict[str, dict[str, Any]]:
        """{command: {dest: value}} for the settings box."""
        return {
            command.name: {option.dest: option.ui_default for option in command.options}
            for command in self.commands
        }

    @property
    def defaults_hash(self) -> str:
        """Short fingerprint of ui_defaults. It goes into the browser's storage key
        for this plugin's settings, so changing the plugin's config starts them fresh."""
        encoded = json.dumps(self.ui_defaults, sort_keys=True).encode()
        return hashlib.sha1(encoded).hexdigest()[:8]
