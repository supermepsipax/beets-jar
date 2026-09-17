import logging
import yaml
from pathlib import Path
from beets import config as beets_config

logger = logging.getLogger("beets")


def get_config_text() -> str | None:

    config_dir = Path(beets_config.config_dir(), "config.yaml")
    yaml_text = config_dir.read_text()

    try:
        yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        logger.error(f"Unable to parse configuration file located at: {config_dir}")
        return None
    return yaml_text
