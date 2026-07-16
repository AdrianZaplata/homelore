import argparse
from datetime import UTC, datetime
from pathlib import Path

from homelore.config import api_key_present, load_env_file, resolve_db_path
from homelore.demo import demo_memories
from homelore.domain import ImportResult
from homelore.embedding import LocalEmbedder
from homelore.extraction import ClaudeExtractor
from homelore.mcp_server import build_server
from homelore.memories_file import read_memories_file
from homelore.service import MISSING_KEY_MESSAGE, HomeloreService, MissingApiKeyError
from homelore.store import MemoryStore
from homelore.summarization import ClaudeSummarizer


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(prog="homelore", description="Self-hosted family memory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Run the MCP server over stdio")
    import_ = subparsers.add_parser(
        "import",
        help="Bulk-import a memories file: one JSON object per line with"
        " text, author, and optional created_at/event_date",
    )
    import_.add_argument("file", help="Path to the memories file")
    reindex = subparsers.add_parser(
        "reindex",
        help="Rebuild the derived indexes from the memory log:"
        " retries failed extractions, never touches the memories themselves",
    )
    reindex.add_argument(
        "--full",
        action="store_true",
        help="Re-extract every memory, not just failed ones (applies extraction improvements)",
    )
    demo = subparsers.add_parser(
        "demo",
        help="Build a database of the fictional Demo Family from the bundled fixtures"
        " — a runnable instance with no real family data (needs an API key)",
    )
    demo.add_argument(
        "--db-path",
        default="homelore-demo.db",
        help="Where to build the demo database (default: ./homelore-demo.db,"
        " deliberately never your real database)",
    )
    for subparser in (serve, import_, reindex):
        subparser.add_argument(
            "--db-path", help="SQLite file (default: $HOMELORE_DB_PATH or ./homelore.db)"
        )
    args = parser.parse_args()

    # No key is not fatal: recall keeps working, and remember explains what to set.
    has_key = api_key_present()
    db_path = (
        _demo_db_path(args.db_path, has_key)
        if args.command == "demo"
        else resolve_db_path(args.db_path)
    )
    service = HomeloreService(
        store=MemoryStore.open(db_path),
        embedder=LocalEmbedder(),
        extractor=ClaudeExtractor() if has_key else None,
        summarizer=ClaudeSummarizer() if has_key else None,
        clock=_utc_now,
    )
    try:
        if args.command == "serve":
            build_server(service).run(transport="stdio")
        elif args.command == "import":
            _report_import(service.import_memories(read_memories_file(Path(args.file))))
        elif args.command == "demo":
            _demo(service, db_path)
        else:
            _reindex(service, full=args.full)
    except (MissingApiKeyError, ValueError, OSError) as error:
        # Config and input problems (missing key, unreadable or malformed
        # memories file) are the user's to fix — no traceback needed.
        raise SystemExit(str(error)) from error


def _demo_db_path(cli_value: str, has_key: bool) -> Path:
    """Where the demo build lands — always its own file, so the fictional
    Demo Family never lands in a real database. Validated before the store is
    opened, which would create the file."""
    path = Path(cli_value).expanduser()
    if path.exists():
        raise SystemExit(
            f"{path} already exists — pass a fresh --db-path, or delete it to rebuild."
        )
    if not has_key:
        raise SystemExit(MISSING_KEY_MESSAGE)
    return path


def _demo(service: HomeloreService, db_path: Path) -> None:
    _report_import(service.import_memories(demo_memories()))
    print(f"Demo Family database ready at {db_path}.")
    print(f"Explore it: homelore serve --db-path {db_path}")


def _report_import(result: ImportResult) -> None:
    line = f"Imported {result.imported} memories."
    if result.extraction_pending:
        line += (
            f" {result.extraction_pending} await an extraction retry —"
            " run 'homelore reindex' to heal them."
        )
    print(line)


def _reindex(service: HomeloreService, full: bool) -> None:
    result = service.reindex(full=full)
    line = f"Re-extracted {result.reextracted} memories."
    if result.failed:
        line += f" {result.failed} failed — re-run 'homelore reindex' to retry them."
    print(line)
