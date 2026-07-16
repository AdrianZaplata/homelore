import os
from pathlib import Path

from dotenv import load_dotenv

DB_PATH_ENV_VAR = "HOMELORE_DB_PATH"
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"


def load_env_file() -> None:
    """Load ./.env into the environment; a variable already set wins.

    The working directory is where the MCP client started the server — the
    same place the default database lands — so a project can keep its key in
    a git-ignored .env next to its homelore.db instead of in client config.
    A missing .env is simply no configuration.
    """
    load_dotenv(Path.cwd() / ".env")


def api_key_present() -> bool:
    """Whether the Anthropic key extraction needs is configured."""
    return bool(os.environ.get(API_KEY_ENV_VAR))


def resolve_db_path(cli_value: str | None = None) -> Path:
    """Database path: CLI flag, then $HOMELORE_DB_PATH, then ./homelore.db.

    The default is the current working directory, so an MCP client launched
    from a project keeps that project's memories next to it.
    """
    explicit = cli_value or os.environ.get(DB_PATH_ENV_VAR)
    if explicit:
        return Path(explicit).expanduser()
    return Path.cwd() / "homelore.db"
