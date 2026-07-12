import os
from pathlib import Path

import platformdirs

DB_PATH_ENV_VAR = "HOMELORE_DB_PATH"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"


def api_key_present() -> bool:
    """Whether the Anthropic key extraction needs is configured."""
    return bool(os.environ.get(API_KEY_ENV_VAR))


def resolve_db_path(cli_value: str | None = None) -> Path:
    """Database path: CLI flag, then $HOMELORE_DB_PATH, then the per-user default."""
    explicit = cli_value or os.environ.get(DB_PATH_ENV_VAR)
    if explicit:
        return Path(explicit).expanduser()
    return Path(platformdirs.user_data_dir("homelore")) / "homelore.db"
