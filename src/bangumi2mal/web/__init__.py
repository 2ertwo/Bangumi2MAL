from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, cast

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from ..clients import MalOAuth
from ..config import Settings
from ..reporting import export_run
from ..runtime import build_database, build_mal_client, build_sync_service
from ..sync_service import SyncAlreadyRunning


F = TypeVar("F", bound=Callable[..., Any])
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


def login_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("authenticated"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return cast(F, wrapped)


def create_app(settings: Optional[Settings] = None) -> Flask:
    settings = settings or Settings.from_env()
    errors = settings.configuration_errors(require_web=True)
    if errors:
        raise RuntimeError("Invalid configuration: " + "; ".join(errors))
    settings.ensure_directories()
    app = Flask(__name__, template_folder="templates")
    app.config.update(
        SECRET_KEY=settings.flask_secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.session_cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    database = build_database(settings)
    with database.connect() as connection:
        connection.execute(
            """UPDATE sync_runs
            SET status = 'failed', finished_at = datetime('now'),
                message = 'Web process restarted before the sync completed'
            WHERE status = 'running'"""
        )
    app.extensions["bangumi2mal_settings"] = settings
    app.extensions["bangumi2mal_database"] = database

    @app.context_processor
    def template_context() -> dict[str, Any]:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    @app.before_request
    def check_csrf() -> None:
        if request.method == "POST":
            expected = session.get("csrf_token", "")
            supplied = request.form.get("csrf_token", "")
            if not expected or not secrets.compare_digest(expected, supplied):
                abort(400, "Invalid CSRF token")

    @app.after_request
    def security_headers(response: Any) -> Any:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' https://cdn.jsdelivr.net; "
            "script-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https:; "
            "form-action 'self' https://myanimelist.net; frame-ancestors 'none'"
        )
        return response

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if request.method == "POST":
            remote = request.remote_addr or "unknown"
            now = time.time()
            attempts = LOGIN_ATTEMPTS[remote]
            while attempts and attempts[0] < now - 300:
                attempts.popleft()
            if len(attempts) >= 5:
                flash("Too many attempts. Try again in a few minutes.", "danger")
                return render_template("login.html"), 429
            if check_password_hash(settings.web_password_hash, request.form.get("password", "")):
                attempts.clear()
                session.clear()
                session["authenticated"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                target = request.args.get("next", "")
                if not target.startswith("/") or target.startswith("//"):
                    target = url_for("dashboard")
                return redirect(target)
            attempts.append(now)
            flash("Incorrect password.", "danger")
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout() -> Any:
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def dashboard() -> Any:
        token = database.get_token("mal")
        runs = database.list_runs(20)
        scheduler = app.extensions.get("bangumi2mal_scheduler")
        job = scheduler.get_job("automatic-sync") if scheduler else None
        return render_template("dashboard.html", runs=runs, token=token, job=job, settings=settings)

    def run_in_background(dry_run: bool, source: str) -> None:
        with app.app_context():
            try:
                service = build_sync_service(settings, database)
                result = service.run(dry_run=dry_run, source=source)
                export_run(result, settings.reports_dir)
            except SyncAlreadyRunning:
                app.logger.info("Skipped %s sync because another run is active", source)
            except Exception:
                app.logger.exception("Background sync failed")

    def start_sync(dry_run: bool, source: str) -> bool:
        if database.has_running_run():
            return False
        thread = threading.Thread(target=run_in_background, args=(dry_run, source), daemon=True)
        thread.start()
        return True

    @app.post("/sync")
    @login_required
    def start_manual_sync() -> Any:
        dry_run = request.form.get("mode", "dry-run") != "live"
        if start_sync(dry_run, "web"):
            flash("Sync started. Refresh shortly to see the result.", "success")
        else:
            flash("A sync is already running.", "warning")
        return redirect(url_for("dashboard"))

    @app.get("/runs/<run_id>")
    @login_required
    def run_detail(run_id: str) -> Any:
        run = database.get_run(run_id)
        if run is None:
            abort(404)
        return render_template("run_detail.html", run=run, items=database.get_run_items(run_id))

    @app.post("/items/<int:item_id>/map")
    @login_required
    def map_item(item_id: int) -> Any:
        item = database.get_item(item_id)
        if item is None:
            abort(404)
        detail_url = url_for(
            "run_detail", run_id=item["run_id"], _anchor=f"item-{item_id}"
        )
        try:
            mal_id = int(request.form.get("mal_id", ""))
            if mal_id <= 0:
                raise ValueError
        except ValueError:
            flash("MAL ID must be a positive integer.", "danger")
            return redirect(detail_url)
        try:
            anime = build_mal_client(settings, database).get_anime(mal_id)
            database.save_mapping(
                int(item["bangumi_id"]),
                mal_id,
                str(item["bangumi_title"]),
                str(anime.get("title") or ""),
                source="manual",
            )
        except Exception as exc:
            flash(f"Could not validate that MAL ID: {exc}", "danger")
            return redirect(detail_url)
        flash("Mapping saved. Confirm the remaining items, then retry the dry run.", "success")
        return redirect(detail_url)

    @app.get("/mappings")
    @login_required
    def mappings() -> Any:
        return render_template("mappings.html", mappings=database.list_mappings())

    @app.post("/mappings/<int:bangumi_id>/delete")
    @login_required
    def delete_mapping(bangumi_id: int) -> Any:
        database.delete_mapping(bangumi_id)
        flash("Mapping removed.", "success")
        return redirect(url_for("mappings"))

    @app.get("/oauth/mal/start")
    @login_required
    def mal_oauth_start() -> Any:
        oauth = MalOAuth(settings.mal_client_id, settings.mal_client_secret, settings.mal_redirect_uri)
        verifier = oauth.create_code_verifier()
        state = secrets.token_urlsafe(24)
        session["mal_oauth_verifier"] = verifier
        session["mal_oauth_state"] = state
        return redirect(oauth.authorization_url(verifier, state))

    @app.get("/oauth/mal/callback")
    @login_required
    def mal_oauth_callback() -> Any:
        if not secrets.compare_digest(request.args.get("state", ""), session.pop("mal_oauth_state", "")):
            abort(400, "OAuth state mismatch")
        verifier = session.pop("mal_oauth_verifier", "")
        code = request.args.get("code", "")
        oauth = MalOAuth(settings.mal_client_id, settings.mal_client_secret, settings.mal_redirect_uri)
        token = oauth.exchange_code(code, verifier)
        database.save_token("mal", str(token["access_token"]), str(token.get("refresh_token") or ""), int(time.time()) + int(token.get("expires_in", 3600)))
        flash("MyAnimeList authorization saved.", "success")
        return redirect(url_for("dashboard"))

    if settings.auto_sync_enabled:
        scheduler = BackgroundScheduler(timezone="UTC", daemon=True)
        scheduler.add_job(lambda: start_sync(False, "scheduler"), "interval", hours=settings.auto_sync_hours, id="automatic-sync", max_instances=1, coalesce=True)
        scheduler.start()
        app.extensions["bangumi2mal_scheduler"] = scheduler

    return app
