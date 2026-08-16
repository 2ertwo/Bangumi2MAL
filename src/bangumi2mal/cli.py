from __future__ import annotations

import argparse
import getpass
import logging
import secrets
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from werkzeug.security import generate_password_hash

from .clients import BangumiClient, MalOAuth
from .config import Settings
from .reporting import export_run
from .runtime import build_database, build_mal_client, build_sync_service


def _settings() -> Settings:
    return Settings.from_env(Path(".env"))


def _configure_logging(settings: Settings) -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def command_check_config(args: argparse.Namespace) -> int:
    settings = _settings()
    errors = settings.configuration_errors(require_web=args.web)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Configuration is complete.")
    if args.remote:
        database = build_database(settings)
        bangumi = BangumiClient(settings.bangumi_access_token, settings.bangumi_user_agent)
        mal = build_mal_client(settings, database)
        bangumi_user = bangumi.get_user(settings.bangumi_username)
        mal_user = mal.get_me()
        print(f"Bangumi: {bangumi_user.get('nickname') or bangumi_user.get('username')}")
        print(f"MyAnimeList: {mal_user.get('name')}")
    return 0


def command_init_db(_args: argparse.Namespace) -> int:
    database = build_database(_settings())
    print(f"Initialized database: {database.path}")
    return 0


def command_hash_password(_args: argparse.Namespace) -> int:
    password = getpass.getpass("Web password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if not password or password != confirmation:
        print("Passwords are empty or do not match.", file=sys.stderr)
        return 1
    print(generate_password_hash(password))
    return 0


def command_generate_secret(_args: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(48))
    return 0


def command_auth_mal(_args: argparse.Namespace) -> int:
    settings = _settings()
    if not settings.mal_client_id:
        print("MAL_CLIENT_ID is not configured.", file=sys.stderr)
        return 1
    database = build_database(settings)
    oauth = MalOAuth(settings.mal_client_id, settings.mal_client_secret, settings.mal_redirect_uri)
    verifier = oauth.create_code_verifier()
    state = secrets.token_urlsafe(24)
    url = oauth.authorization_url(verifier, state)
    print("Open this URL and authorize the application:\n")
    print(url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    pasted = input("\nPaste the full callback URL (or just the code): ").strip()
    if "://" in pasted:
        query = parse_qs(urlparse(pasted).query)
        if query.get("state", [state])[0] != state:
            print("OAuth state mismatch.", file=sys.stderr)
            return 1
        code = query.get("code", [""])[0]
    else:
        code = pasted
    if not code:
        print("No authorization code was provided.", file=sys.stderr)
        return 1
    token = oauth.exchange_code(code, verifier)
    database.save_token("mal", str(token["access_token"]), str(token.get("refresh_token") or ""), int(time.time()) + int(token.get("expires_in", 3600)))
    print("MyAnimeList authorization saved.")
    return 0


def command_sync(args: argparse.Namespace) -> int:
    settings = _settings()
    errors = settings.configuration_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _configure_logging(settings)
    database = build_database(settings)
    service = build_sync_service(settings, database)
    run = service.run(dry_run=args.dry_run, source="cli")
    report_path = export_run(run, settings.reports_dir)
    counts = run.counts
    print(f"Run {run.run_id}: {run.status}; total={counts['total']} synced={counts['synced']} planned={counts['planned']} skipped={counts['skipped']} unresolved={counts['unresolved']} failed={counts['failed']}")
    print(f"Reports: {report_path}")
    return 2 if counts["failed"] else 0


def command_serve(args: argparse.Namespace) -> int:
    from .web import create_app
    settings = _settings()
    errors = settings.configuration_errors(require_web=True)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    _configure_logging(settings)
    app = create_app(settings)
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bangumi2mal")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check-config", help="validate configuration")
    check.add_argument("--web", action="store_true", help="also require web settings")
    check.add_argument("--remote", action="store_true", help="verify both API accounts")
    check.set_defaults(func=command_check_config)
    init_db = subparsers.add_parser("init-db", help="initialize the SQLite database")
    init_db.set_defaults(func=command_init_db)
    password = subparsers.add_parser("hash-password", help="generate WEB_PASSWORD_HASH")
    password.set_defaults(func=command_hash_password)
    secret = subparsers.add_parser("generate-secret", help="generate FLASK_SECRET_KEY")
    secret.set_defaults(func=command_generate_secret)
    auth_mal = subparsers.add_parser("auth-mal", help="authorize MyAnimeList with OAuth")
    auth_mal.set_defaults(func=command_auth_mal)
    sync = subparsers.add_parser("sync", help="run one Bangumi to MAL sync")
    sync.add_argument("--dry-run", action="store_true", help="calculate without writing to MAL")
    sync.set_defaults(func=command_sync)
    serve = subparsers.add_parser("serve", help="run the Flask web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=5000)
    serve.set_defaults(func=command_serve)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(args.func(args))
    except KeyboardInterrupt:
        raise SystemExit(130)
