"""Reading, checking and saving the config.yaml the configuration page edits."""

import logging
from pathlib import Path
from typing import Any

import yaml
from beets import config as beets_config
from confuse import ConfigError

logger = logging.getLogger("beets")

KEYMAPS = ["default", "vim"]


def config_path() -> Path:
    return Path(beets_config.config_dir(), "config.yaml")


def parse_yaml(text: str) -> tuple[Any, dict | None]:
    """(data, None) when `text` parses, otherwise (None, problem), where problem
    is {"line", "col", "message"} with 1-based positions for the editor."""
    try:
        return yaml.safe_load(text), None
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        return None, {
            "line": mark.line + 1 if mark else 1,
            "col": mark.column + 1 if mark else 1,
            "message": error.problem or str(error),
        }
    except yaml.YAMLError as error:
        return None, {"line": 1, "col": 1, "message": str(error)}


def read_config_text() -> str | None:
    """config.yaml's text, or None if it doesn't parse."""
    path = config_path()
    text = path.read_text()
    _, problem = parse_yaml(text)
    if problem:
        logger.error(f"Unable to parse configuration file located at: {path}")
        return None
    return text


def save_config(text: str, data: Any) -> None:
    """Write config.yaml and apply it to the running server. `data` is `text`
    already parsed by parse_yaml()."""
    config_path().write_text(text)
    beets_config.set(data)


def editor_keymap() -> str:
    try:
        return beets_config["jar"]["editor"]["keymap"].as_choice(KEYMAPS)
    except ConfigError:
        logger.warning("jar.editor.keymap must be one of %s; using default", KEYMAPS)
        return "default"
