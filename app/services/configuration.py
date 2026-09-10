import logging
import os
import yaml
from pathlib import Path

log = logging.getLogger("beets")

def get_config_text() -> str | None:

    config_dir = Path(os.environ["BEETSDIR"], "config.yaml")
    yaml_text = config_dir.read_text()

    try:
        yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        log.error(f"Unable to parse configuration file located at: {config_dir}" )
        return None
    return yaml_text

