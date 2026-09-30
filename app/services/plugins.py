from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

import confuse
import yaml
from beets import config, plugins
from beets.plugins import BeetsPlugin
from beets.ui import Subcommand

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "plugin_manifest.yaml"

Target = Literal["album", "item", "flag"]
TARGETS = ("album", "item", "flag")
# optparse actions whose value we know how to build from a form field
SUPPORTED_ACTIONS = {"store", "store_true", "store_false", "count"}


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


# ---------- manifest ----------


@cache
def load_manifest() -> dict[str, dict]:
    """Parsed plugin_manifest.yaml, cached for the life of the server."""
    with MANIFEST_PATH.open() as f:
        return yaml.safe_load(f) or {}


def _wanted_names() -> list[str]:
    try:
        return config["jar"]["plugins"].as_str_seq()
    except confuse.NotFoundError:
        return []


# ---------- side panel ----------


def get_panel_plugins() -> list[PanelPlugin]:
    """Side-panel plugins, in `jar.plugins` order (or manifest order)."""
    manifest = load_manifest()
    loaded = {plugin.name: plugin for plugin in plugins.find_plugins()}
    panel = []
    for name in _wanted_names() or list(manifest):
        if name in manifest and name in loaded:
            panel_plugin = _panel_plugin(name, loaded[name], manifest[name] or {})
            if panel_plugin.commands:
                panel.append(panel_plugin)
    return panel


def get_panel_plugin(name: str) -> PanelPlugin | None:
    return next((p for p in get_panel_plugins() if p.name == name), None)


def ui_defaults(plugin: PanelPlugin) -> dict[str, dict[str, Any]]:
    """{command: {dest: value}} for the settings box. Bools stay bools; the rest
    become strings so they compare cleanly with <input> values in the browser."""
    return {
        command.name: {option.dest: _ui_value(option) for option in command.options}
        for command in plugin.commands
    }


def _ui_value(option: PluginOption) -> Any:
    if option.type == "bool":
        return bool(option.default)
    return "" if option.default is None else str(option.default)


def defaults_hash(defaults: dict) -> str:
    """Short fingerprint of ui_defaults(). It goes into the browser's storage key
    for a plugin's settings, so changing that plugin's config starts them fresh."""
    return hashlib.sha1(json.dumps(defaults, sort_keys=True).encode()).hexdigest()[:8]


def _panel_plugin(name: str, plugin: BeetsPlugin, spec: dict) -> PanelPlugin:
    # commands() builds option defaults from the current config, so call it fresh
    subcommands = {sub.name: sub for sub in plugin.commands()}
    commands = []
    for command_name, command_spec in (spec.get("commands") or {}).items():
        command_spec = command_spec or {}
        sub = subcommands.get(command_name)
        target = command_spec.get("target")
        if sub is None or target not in TARGETS:
            continue
        commands.append(
            PluginCommand(
                name=command_name,
                target=target,
                options=tuple(_options(plugin, sub, command_spec)),
                fixed=dict(command_spec.get("fixed") or {}),
            )
        )
    return PanelPlugin(name, tuple(commands))


def _options(plugin: BeetsPlugin, sub: Subcommand, command_spec: dict):
    """The manifest-listed options, with type/help/default from the parser."""
    by_dest = {}
    for option in sub.parser._get_all_options():
        # Paired flags share a dest (--force/--no-force): the first one describes it
        if option.dest and option.dest not in by_dest:
            by_dest[option.dest] = option
    config_keys = command_spec.get("config") or {}
    for dest in command_spec.get("options") or []:
        option = by_dest.get(dest)
        if option is None or option.action not in SUPPORTED_ACTIONS:
            continue
        yield PluginOption(
            dest=dest,
            type=_infer_type(option),
            default=_default(plugin, sub, dest, config_keys.get(dest)),
            help=option.help,
        )


def _infer_type(option) -> str:
    # store_true/store_false/count actions don't set `option.type`,
    # so the action itself is what tells us the real value type
    if option.action in ("store_true", "store_false"):
        return "bool"
    if option.action == "count" or option.type == "int":
        return "int"
    if option.type == "float":
        return "float"
    return "string"


def _default(plugin: BeetsPlugin, sub: Subcommand, dest: str, config_key: str | None) -> Any:
    if config_key:
        try:
            return plugin.config[config_key].get()
        except confuse.ConfigError:
            pass
    # parser.defaults already maps "no default" to None and includes set_defaults()
    return sub.parser.defaults.get(dest)


# ---------- running ----------


def find_subcommand(plugin_name: str, command_name: str) -> Subcommand | None:
    for plugin in plugins.find_plugins():
        if plugin.name == plugin_name:
            return next((sub for sub in plugin.commands() if sub.name == command_name), None)
    return None


def coerce(option: PluginOption, raw: str) -> Any:
    """Form value -> Python value. Raises ValueError on bad numbers."""
    raw = raw.strip()
    match option.type:
        case "bool":
            return raw in ("1", "true", "on")
        case "int":
            return int(raw)
        case "float":
            return float(raw)
        case _:
            return raw


def read_overrides(command: PluginCommand, form: Mapping, prefix: str) -> dict[str, Any]:
    """Options the user changed, read from `<prefix>.<dest>` form fields.

    The chosen command's settings are always in the form (x-show only hides
    them), so a missing checkbox means "unticked", i.e. False.
    Values equal to the default are dropped, so untouched options keep beets'
    own behaviour (e.g. a None default meaning "use the config").
    Raises ValueError for a malformed number.
    """
    overrides = {}
    for option in command.options:
        raw = form.get(f"{prefix}.{option.dest}")
        if option.type == "bool":
            value = raw is not None and coerce(option, str(raw))
        elif raw is None or not str(raw).strip():
            continue
        else:
            value = coerce(option, str(raw))
        default = bool(option.default) if option.type == "bool" else option.default
        if value != default:
            overrides[option.dest] = value
    return overrides
