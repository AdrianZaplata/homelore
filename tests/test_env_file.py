"""A .env file in the working directory configures the server (config seam).

The CLI loads it on startup so an MCP client config needs no inline secrets:
the key lives in a git-ignored .env next to the database. The real
environment always wins — .env is a fallback, never an override.
"""

import os
from pathlib import Path

import pytest

from homelore.config import API_KEY_ENV_VAR, DB_PATH_ENV_VAR, load_env_file


@pytest.fixture
def scrubbed_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Both variables absent, with teardown that also removes any the test
    creates — delenv on an already-absent variable registers no undo, so
    set-then-delete is what makes load_env_file's writes get cleaned up."""
    for variable in (API_KEY_ENV_VAR, DB_PATH_ENV_VAR):
        monkeypatch.setenv(variable, "scrubbed")
        monkeypatch.delenv(variable)
    return monkeypatch


def test_env_file_in_working_directory_reaches_the_environment(
    tmp_path: Path, scrubbed_env: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        f"{API_KEY_ENV_VAR}=sk-ant-from-dotenv\n{DB_PATH_ENV_VAR}=family.db\n"
    )
    scrubbed_env.chdir(tmp_path)

    load_env_file()

    assert os.environ[API_KEY_ENV_VAR] == "sk-ant-from-dotenv"
    assert os.environ[DB_PATH_ENV_VAR] == "family.db"


def test_real_environment_wins_over_env_file(
    tmp_path: Path, scrubbed_env: pytest.MonkeyPatch
) -> None:
    scrubbed_env.setenv(API_KEY_ENV_VAR, "sk-ant-from-environment")
    (tmp_path / ".env").write_text(f"{API_KEY_ENV_VAR}=sk-ant-from-dotenv\n")
    scrubbed_env.chdir(tmp_path)

    load_env_file()

    assert os.environ[API_KEY_ENV_VAR] == "sk-ant-from-environment"


def test_missing_env_file_is_no_configuration(
    tmp_path: Path, scrubbed_env: pytest.MonkeyPatch
) -> None:
    scrubbed_env.chdir(tmp_path)

    load_env_file()

    assert API_KEY_ENV_VAR not in os.environ
