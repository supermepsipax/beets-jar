"""Side-panel plugins, as read from plugin_manifest.yaml and the plugins' own parsers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Target = Literal["album", "item", "flag"]


@dataclass(frozen=True)
class PluginOption:
    dest: str
    type: str  # bool | int | float | string
    default: Any  # what the command uses if the user changes nothing
    help: str | None = None


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
