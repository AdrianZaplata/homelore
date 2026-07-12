import argparse
from datetime import UTC, datetime

from homelore.config import api_key_present, resolve_db_path
from homelore.embedding import LocalEmbedder
from homelore.extraction import ClaudeExtractor
from homelore.mcp_server import build_server
from homelore.service import HomeloreService
from homelore.store import MemoryStore


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(prog="homelore", description="Self-hosted family memory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the MCP server over stdio")
    serve.add_argument(
        "--db-path", help="SQLite file (default: $HOMELORE_DB_PATH or user data dir)"
    )
    args = parser.parse_args()

    # No key is not fatal: recall keeps working, and remember explains what to set.
    service = HomeloreService(
        store=MemoryStore.open(resolve_db_path(args.db_path)),
        embedder=LocalEmbedder(),
        extractor=ClaudeExtractor() if api_key_present() else None,
        clock=_utc_now,
    )
    build_server(service).run(transport="stdio")
