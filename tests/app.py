from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import hmac
import os
from pathlib import Path
import secrets
import time

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (
    APP_PORT,
    APP_VERSION,
    IS_PRODUCTION,
    MAX_REPORT_PAGES,
    MAX_UPLOAD_MB,
    MAX_USER_UPLOADS_PER_HOUR,
    OLLAMA_ENABLED,
    PROXY_HOPS,
    REPORTS_DIR,
    SECURE_COOKIES,
    TRUST_PROXY,
    UPLOAD_DIR,
)
from engine import db
from engine.analysis import compare, overview
from engine.news import search as news_search, macro_search as macro_news_search
from engine.ollama import explain
from engine.risk import assess
from engine.guardian import check as guardian_check
from engine.scanner import scan
from engine.stock import analyze as stock_analyze, ticker_for
from engine.indicators_vsa import analyze_company as analyze_vsa_company, screen_companies as screen_vsa_companies
from engine.trading_risk import analyze_trading_risk
from engine.valuation import value_company
from engine.evidence import get_evidence
from engine.portfolio_risk import analyze_portfolio
from engine.research import anomalies as research_anomalies, research_brief
from engine.macro import macro_snapshot
from engine.dashboard_macro import dashboard_macro_snapshot
from engine.stock import market_snapshot, world_market_snapshot
from engine.event_probability.service import catalog_options, analyze_factor
from engine.event_probability import db as event_db
from engine.system_health import provider_snapshot, record_provider
from engine.report_reader import SUPPORTED as SUPPORTED_REPORT_TYPES
from engine.web_security import SlidingWindowLimiter, safe_path_segment, safe_uploaded_name, validate_upload_content
from engine import auth, jobs, watchlist
from engine.observability import configure_logging, log_request, new_request_id

app = Flask(__name__)
configure_logging()
if TRUST_PROXY:
    # Enable only behind a known reverse proxy. Render terminates TLS and
    # supplies one trusted forwarding hop before traffic reaches Gunicorn.
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=PROXY_HOPS,
        x_proto=PROXY_HOPS,
        x_host=PROXY_HOPS,
        x_port=PROXY_HOPS,
    )

app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
app.config.update(
    SECRET_KEY=auth.session_secret(),
    SESSION_COOKIE_NAME="solvai_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SECURE_COOKIES,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    PREFERRED_URL_SCHEME="https" if SECURE_COOKIES else "http",
)

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()
auth.init_auth_db()
watchlist.init_db()
auth.bootstrap_admin_from_env()

# Startup no longer performs a full scan. Use scan.bat or POST /api/scan for explicit indexing.
# This prevents every app restart from re-verifying the entire report library.
STARTUP_SCAN = {"success": True, "status": "ready", "scan_skipped": True}

PUBLIC_ENDPOINTS = {
    "login",
    "api_health",
    "api_ready",
    "api_auth_csrf",
    "api_auth_login",
    "api_auth_register",
}

PASSWORD_RESET_ENDPOINTS = {
    "account_security",
    "api_auth_change_password",
    "api_auth_logout",
    "api_auth_me",
    "api_auth_sessions",
    "api_auth_revoke_session",
}

_AUTH_LIMITER = SlidingWindowLimiter()
_UPLOAD_LIMITER = SlidingWindowLimiter()


def _client_address():
    return request.remote_addr or "unknown"


def _client_agent():
    return request.headers.get("User-Agent", "Unknown device")


def _has_role(*roles):
    return bool(g.current_user and g.current_user.get("role") in set(roles))


def _forecast_scope():
    """Keep all forecast reads and writes inside the signed-in user's workspace."""
    return {
        "owner_user_id": g.current_user["id"],
        "workspace_id": g.current_user.get("workspace_id") or "default",
    }


def _role_error(*roles):
    readable = " or ".join(role.title() for role in roles)
    return jsonify({"success": False, "error": f"{readable} access is required.", "code": "forbidden"}), 403


def _auth_rate_exceeded(scope, limit, window_seconds):
    """Limit repeated auth work per client on the single-instance deployment."""
    return _AUTH_LIMITER.exceeded(
        scope,
        request.remote_addr or "unknown",
        limit,
        window_seconds,
    )


def _rate_limit_response(message):
    response = jsonify({"success": False, "error": message, "code": "rate_limited"})
    response.status_code = 429
    response.headers["Retry-After"] = "300"
    return response


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _safe_next(value):
    target = str(value or "").strip()
    return target if target.startswith("/") and not target.startswith("//") else "/"


def _registration_enabled():
    default = "0" if IS_PRODUCTION else "1"
    return os.getenv("SOLVAI_ALLOW_REGISTRATION", default).strip().lower() not in {"0", "false", "no"}


@app.before_request
def authenticate_request():
    g.csp_nonce = secrets.token_urlsafe(18)
    g.request_id = new_request_id(request.headers.get("X-Request-ID"))
    g.request_started = time.monotonic()
    if request.endpoint == "static":
        g.current_user = None
        g.current_session = None
        return None
    g.current_user, g.current_session = auth.validate_session(
        session.get("user_id"), session.get("auth_token")
    )
    if session.get("user_id") and not g.current_user:
        session.clear()

    endpoint = request.endpoint or ""
    is_public = endpoint == "static" or endpoint in PUBLIC_ENDPOINTS
    if not is_public and not g.current_user:
        if request.path.startswith("/api/"):
            return jsonify({"success": False, "error": "Sign in to continue.", "code": "authentication_required"}), 401
        return redirect(url_for("login", next=request.full_path.rstrip("?")))

    if (
        g.current_user
        and g.current_user.get("must_reset_password")
        and endpoint not in PASSWORD_RESET_ENDPOINTS
        and endpoint != "static"
    ):
        if request.path.startswith("/api/"):
            return jsonify({
                "success": False,
                "error": "Change your password before continuing.",
                "code": "password_reset_required",
            }), 403
        return redirect(url_for("account_security"))

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "") or request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not supplied or not expected or not hmac.compare_digest(supplied, expected):
            return jsonify({"success": False, "error": "Your session changed. Refresh the page and try again.", "code": "csrf_failed"}), 400


@app.after_request
def secure_response(response):
    nonce = getattr(g, "csp_nonce", "")
    response.headers["Content-Security-Policy"] = "; ".join((
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        "script-src-attr 'none'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if request.path == "/" or request.path == "/login" or request.path.startswith("/api/auth/") or request.path.startswith("/admin/") or request.path.startswith("/account/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Vary"] = "Cookie"
    elif getattr(g, "current_user", None):
        response.headers.setdefault("Cache-Control", "private")
    if app.config.get("SESSION_COOKIE_SECURE"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    if request.endpoint != "static":
        log_request(
            request_id=getattr(g, "request_id", "unknown"),
            method=request.method,
            path=request.path,
            status=response.status_code,
            duration_ms=(time.monotonic() - getattr(g, "request_started", time.monotonic())) * 1000,
        )
    return response


@app.get("/login")
def login():
    if g.current_user:
        return redirect(_safe_next(request.args.get("next")))
    return render_template(
        "auth.html",
        csrf_token=_csrf_token(),
        next_url=_safe_next(request.args.get("next")),
        registration_enabled=_registration_enabled(),
        first_account=auth.user_count() == 0,
        app_version=APP_VERSION,
    )


@app.get("/api/auth/csrf")
def api_auth_csrf():
    return jsonify({"success": True, "csrf_token": _csrf_token()})


@app.post("/api/auth/register")
def api_auth_register():
    if g.current_user:
        return jsonify({"success": False, "error": "Sign out before creating another account.", "code": "already_signed_in"}), 409
    if not _registration_enabled():
        return jsonify({"success": False, "error": "New account registration is disabled.", "code": "registration_disabled"}), 403
    if _auth_rate_exceeded(
        "register",
        max(1, int(os.getenv("SOLVAI_REGISTER_RATE_LIMIT", "5"))),
        3600,
    ):
        return _rate_limit_response("Too many registration attempts. Try again later.")
    body = request.get_json(silent=True) or {}
    try:
        access_request = auth.create_access_request(
            body.get("email"), body.get("password"), body.get("display_name"),
            request_note=body.get("request_note"),
            address=_client_address(), user_agent=_client_agent(),
        )
    except auth.AuthError as exc:
        status = 409 if exc.code in {"email_exists", "request_pending"} else 400
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), status
    return jsonify({
        "success": True,
        "pending_approval": True,
        "request": access_request,
        "message": "Access request submitted. A workspace administrator must approve it before you can sign in.",
    }), 202


@app.post("/api/auth/login")
def api_auth_login():
    if _auth_rate_exceeded(
        "login",
        max(5, int(os.getenv("SOLVAI_LOGIN_RATE_LIMIT", "30"))),
        300,
    ):
        return _rate_limit_response("Too many sign-in attempts. Try again in a few minutes.")
    body = request.get_json(silent=True) or {}
    try:
        user = auth.authenticate(
            body.get("email"), body.get("password"),
            address=_client_address(), user_agent=_client_agent(),
        )
    except auth.AuthError as exc:
        status = 429 if exc.code == "locked" else 401
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), status
    session.clear()
    session.permanent = bool(body.get("remember"))
    session["user_id"] = user["id"]
    session["auth_token"] = auth.start_session(
        user["id"], remember=session.permanent,
        address=_client_address(), user_agent=_client_agent(),
    )
    session["csrf_token"] = secrets.token_urlsafe(32)
    next_url = url_for("account_security") if user.get("must_reset_password") else _safe_next(body.get("next"))
    return jsonify({"success": True, "user": user, "next": next_url})


@app.post("/api/auth/logout")
def api_auth_logout():
    auth.record_logout(g.current_user, (g.current_session or {}).get("id"))
    session.clear()
    return jsonify({"success": True, "next": url_for("login")})


@app.get("/api/auth/me")
def api_auth_me():
    return jsonify({"success": True, "user": g.current_user, "session": g.current_session})


@app.get("/account/security")
def account_security():
    sessions = auth.list_sessions(g.current_user["id"])
    current_id = (g.current_session or {}).get("id")
    for item in sessions:
        item["current"] = item.get("id") == current_id
    return render_template(
        "account_security.html",
        current_user=g.current_user,
        sessions=sessions,
        csrf_token=_csrf_token(),
        app_version=APP_VERSION,
        csp_nonce=g.csp_nonce,
    )


@app.get("/api/auth/sessions")
def api_auth_sessions():
    sessions = auth.list_sessions(g.current_user["id"])
    current_id = (g.current_session or {}).get("id")
    for item in sessions:
        item["current"] = item.get("id") == current_id
    return jsonify({"success": True, "sessions": sessions})


@app.delete("/api/auth/sessions/<int:session_id>")
def api_auth_revoke_session(session_id):
    current = session_id == (g.current_session or {}).get("id")
    if not auth.revoke_session(session_id, user_id=g.current_user["id"]):
        return jsonify({"success": False, "error": "Active session not found.", "code": "not_found"}), 404
    if current:
        session.clear()
    return jsonify({"success": True, "current": current, "next": url_for("login") if current else None})


@app.post("/api/auth/password")
def api_auth_change_password():
    body = request.get_json(silent=True) or {}
    try:
        user = auth.change_password(
            g.current_user["id"], body.get("current_password"), body.get("new_password")
        )
    except auth.AuthError as exc:
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), 400
    remember = bool(session.permanent)
    session.clear()
    session.permanent = remember
    session["user_id"] = user["id"]
    session["auth_token"] = auth.start_session(
        user["id"], remember=remember, address=_client_address(), user_agent=_client_agent()
    )
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"success": True, "user": user, "message": "Password changed and other sessions signed out."})


@app.get("/admin/users")
def admin_users():
    if g.current_user.get("role") != "admin":
        abort(403)
    workspace_id = g.current_user.get("workspace_id") or "default"
    pending_requests = auth.list_access_requests(status="pending", workspace_id=workspace_id)
    return render_template(
        "admin_users.html",
        current_user=g.current_user,
        users=auth.list_users(),
        pending_requests=pending_requests,
        events=auth.recent_login_events(80),
        audits=auth.recent_admin_audit(80),
        csrf_token=_csrf_token(),
        app_version=APP_VERSION,
    )


@app.get("/api/admin/users")
def api_admin_users():
    if g.current_user.get("role") != "admin":
        return jsonify({"success": False, "error": "Administrator access is required."}), 403
    workspace_id = g.current_user.get("workspace_id") or "default"
    return jsonify({
        "success": True,
        "users": auth.list_users(),
        "access_requests": auth.list_access_requests(status="pending", workspace_id=workspace_id),
        "events": auth.recent_login_events(80),
        "audits": auth.recent_admin_audit(80),
    })


@app.get("/api/admin/access-requests")
def api_admin_access_requests():
    if not _has_role("admin"):
        return _role_error("admin")
    status = str(request.args.get("status") or "pending").strip().lower()
    if status == "all":
        status = None
    try:
        rows = auth.list_access_requests(
            status=status,
            workspace_id=g.current_user.get("workspace_id") or "default",
            limit=request.args.get("limit", 200),
        )
    except (auth.AuthError, TypeError, ValueError) as exc:
        code = exc.code if isinstance(exc, auth.AuthError) else "invalid_request"
        return jsonify({"success": False, "error": str(exc) or "Invalid request.", "code": code}), 400
    return jsonify({"success": True, "access_requests": rows})


@app.post("/api/admin/access-requests/<int:request_id>/action")
def api_admin_access_request_action(request_id):
    if not _has_role("admin"):
        return _role_error("admin")
    body = request.get_json(silent=True) or {}
    try:
        result = auth.review_access_request(
            request_id,
            body.get("action"),
            role=body.get("role") or "viewer",
            actor_id=g.current_user["id"],
            decision_note=body.get("decision_note"),
        )
    except auth.AuthError as exc:
        if exc.code == "not_found":
            status = 404
        elif exc.code in {"already_reviewed", "email_exists"}:
            status = 409
        elif exc.code == "forbidden":
            status = 403
        else:
            status = 400
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), status
    return jsonify({"success": True, **result})


@app.post("/api/admin/users")
def api_admin_create_user():
    if not _has_role("admin"):
        return _role_error("admin")
    body = request.get_json(silent=True) or {}
    try:
        user = auth.create_user(
            body.get("email"), body.get("password"), body.get("display_name"),
            role=body.get("role") or "viewer", actor_id=g.current_user["id"],
        )
    except auth.AuthError as exc:
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), 400
    return jsonify({"success": True, "user": user}), 201


@app.post("/api/admin/users/<int:user_id>/action")
def api_admin_user_action(user_id):
    if not _has_role("admin"):
        return _role_error("admin")
    body = request.get_json(silent=True) or {}
    action = str(body.get("action") or "").strip().lower()
    try:
        if action == "activate":
            user = auth.set_active(user_id, True, actor_id=g.current_user["id"])
        elif action == "deactivate":
            user = auth.set_active(user_id, False, actor_id=g.current_user["id"])
        elif action == "unlock":
            user = auth.unlock_user(user_id, actor_id=g.current_user["id"])
        elif action == "set_role":
            user = auth.set_role(user_id, body.get("role"), actor_id=g.current_user["id"])
        elif action == "require_password_reset":
            user = auth.require_password_reset(user_id, actor_id=g.current_user["id"])
        elif action == "revoke_sessions":
            count = auth.admin_revoke_user_sessions(user_id, actor_id=g.current_user["id"])
            return jsonify({"success": True, "revoked": count})
        else:
            return jsonify({"success": False, "error": "Unsupported account action.", "code": "invalid_action"}), 400
    except auth.AuthError as exc:
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), 400
    return jsonify({"success": True, "user": user})


@app.delete("/api/admin/users/<int:user_id>")
def api_admin_delete_user(user_id):
    if not _has_role("admin"):
        return _role_error("admin")
    try:
        auth.delete_user(user_id, actor_id=g.current_user["id"])
    except auth.AuthError as exc:
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), 400
    return jsonify({"success": True})


@app.route("/")
def index():
    return render_template(
        "index.html",
        companies=db.companies(),
        industries=db.industries(),
        current_user=g.current_user,
        csrf_token=_csrf_token(),
        app_version=APP_VERSION,
        csp_nonce=g.csp_nonce,
    )


@app.get("/api/health")
def api_health():
    return jsonify({
        "success": True,
        "status": "ok",
        "version": APP_VERSION,
        "environment": "production" if IS_PRODUCTION else "development",
        "startup_scan": STARTUP_SCAN,
        "authentication": "required",
        "generative_assistant": "enabled" if OLLAMA_ENABLED else "disabled",
    })


@app.get("/api/ready")
def api_ready():
    ready = auth.readiness_check() and event_db.readiness_check() and watchlist.readiness_check()
    payload = {"success": ready, "status": "ready" if ready else "not_ready", "version": APP_VERSION}
    return jsonify(payload), 200 if ready else 503


@app.get("/api/companies")
def api_companies():
    companies=[]
    for row in db.companies():
        item=dict(row)
        ticker=ticker_for(str(item.get("company") or ""))
        item["market_ticker"]=ticker
        item["exchange"]="Vietnam market" if ticker.endswith(".VN") else "Local library"
        companies.append(item)
    return jsonify({"success": True, "companies": companies, "industries": db.industries()})


@app.get("/api/overview/<company>")
def api_overview(company):
    return jsonify(overview(company.upper()))


@app.get("/api/ratios/<company>")
def api_ratios(company):
    data=overview(company.upper())
    if data.get("error"):
        return jsonify(data), 404
    return jsonify({"success":True,"company":data["company"],"latest":data["ratio_views"]["latest"],"market":data["ratio_views"]["market"],"market_basis":data["ratio_views"]["market_basis"],"details":data["market_ratios"]})

@app.get("/api/compare")
def api_compare():
    raw = request.args.get("companies", "")
    companies = [x.strip().upper() for x in raw.split(",") if x.strip()]
    return jsonify(compare(companies))


@app.get("/api/risk/<company>")
def api_risk(company):
    return jsonify(assess(company.upper()))


@app.post("/api/valuation/<company>")
def api_valuation(company):
    """Run a transparent, non-personalized per-share valuation study."""
    body = request.get_json(silent=True) or {}
    assumptions = body.get("assumptions") if isinstance(body.get("assumptions"), dict) else body
    inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else None
    drivers = body.get("drivers") if isinstance(body.get("drivers"), dict) else None
    holding = body.get("holding") if isinstance(body.get("holding"), dict) else None
    try:
        result = value_company(
            company.upper(),
            assumptions=assumptions,
            manual_inputs=inputs,
            forward_drivers=drivers,
            holding_inputs=holding,
        )
        scope = _forecast_scope()
        try:
            result["persistence"] = watchlist.record_valuation(
                scope["owner_user_id"], scope["workspace_id"], result
            )
        except Exception:
            result["persistence"] = {
                "saved": False,
                "reason": "Valuation completed, but history could not be updated.",
            }
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "invalid_assumptions"}), 400


def _watchlist_company(value):
    return safe_path_segment(value, "Company").upper()


@app.get("/api/watchlist")
def api_watchlist():
    scope = _forecast_scope()
    return jsonify({
        "success": True,
        **watchlist.list_watchlist(scope["owner_user_id"], scope["workspace_id"]),
    })


@app.post("/api/watchlist/<company>")
def api_watchlist_upsert(company):
    scope = _forecast_scope()
    try:
        item = watchlist.upsert_watchlist(
            scope["owner_user_id"], scope["workspace_id"], _watchlist_company(company),
            request.get_json(silent=True) or {},
        )
        return jsonify({"success": True, "item": item})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "valuation_required"}), 400


@app.delete("/api/watchlist/<company>")
def api_watchlist_remove(company):
    scope = _forecast_scope()
    try:
        removed = watchlist.remove_watchlist(
            scope["owner_user_id"], scope["workspace_id"], _watchlist_company(company)
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "invalid_company"}), 400
    return jsonify({"success": True, "removed": removed})


@app.get("/api/valuation/history/<company>")
def api_valuation_history(company):
    scope = _forecast_scope()
    try:
        limit = int(request.args.get("limit", 30))
        history = watchlist.list_history(
            scope["owner_user_id"], scope["workspace_id"], _watchlist_company(company), limit
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc) or "Invalid history request.", "code": "invalid_request"}), 400
    return jsonify({"success": True, "company": company.upper(), "history": history})


@app.get("/api/alerts")
def api_alerts():
    scope = _forecast_scope()
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    unread_only = request.args.get("unread", "0").strip().lower() in {"1", "true", "yes"}
    return jsonify({
        "success": True,
        **watchlist.list_alerts(scope["owner_user_id"], scope["workspace_id"], limit, unread_only),
    })


@app.post("/api/alerts/<int:alert_id>/read")
def api_alert_read(alert_id):
    scope = _forecast_scope()
    changed = watchlist.mark_alert_read(
        scope["owner_user_id"], scope["workspace_id"], alert_id
    )
    return jsonify({"success": True, "changed": changed})


@app.post("/api/alerts/read-all")
def api_alert_read_all():
    scope = _forecast_scope()
    changed = watchlist.mark_alert_read(
        scope["owner_user_id"], scope["workspace_id"]
    )
    return jsonify({"success": True, "changed": changed})


@app.get("/api/evidence/<company>")
def api_evidence(company):
    metric = request.args.get("metric", "revenue")
    basis = request.args.get("basis", "latest")
    return jsonify(get_evidence(company.upper(), metric, basis))


@app.get("/api/anomalies/<company>")
def api_anomalies(company):
    return jsonify(research_anomalies(company.upper()))


@app.get("/api/research/brief/<company>")
def api_research_brief(company):
    return jsonify(research_brief(company.upper()))


@app.post("/api/portfolio/risk")
def api_portfolio_risk():
    body = request.get_json(silent=True) or {}
    holdings = body.get("holdings", [])
    return jsonify(analyze_portfolio(holdings))


@app.get("/api/risk/trading/<company>")
def api_trading_risk(company):
    def _num(name, default=None, cast=float):
        raw=request.args.get(name, default)
        if raw in (None, ""):
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default
    data=analyze_trading_risk(
        company.upper(),
        entry_price=_num("entry"),
        account_equity=_num("equity"),
        risk_pct=_num("risk_pct", 1.0),
        target_r_multiple=_num("target_r", 2.0),
        horizon=_num("horizon", 20, int),
        side=str(request.args.get("side", "long")),
        sizing_method=str(request.args.get("sizing_method", "fixed-fractional")),
    )
    return jsonify(data)


@app.get("/api/guardian")
def api_guardian():
    return jsonify(guardian_check())


@app.get("/api/stock/<company>")
def api_stock(company):
    return jsonify(stock_analyze(company.upper()))


def _indicator_statement_context(company):
    """Return only auditable statement context needed by the VSA score."""
    normalized = str(company or "").strip().upper()
    try:
        company_overview = overview(normalized)
    except Exception:
        company_overview = {"error": "Statement evidence is temporarily unavailable."}
    if company_overview.get("error"):
        return {
            "available": False,
            "company": normalized,
            "note": "No indexed financial statement is connected to this market symbol yet.",
        }
    coverage = company_overview.get("coverage") or {}
    available_metrics = int(coverage.get("available_metrics") or 0)
    total_metrics = max(1, int(coverage.get("total_metrics") or 1))
    try:
        risk_flags = (assess(normalized) or {}).get("flags") or []
    except Exception:
        risk_flags = []
    latest_report = company_overview.get("latest_report") or {}
    return {
        "available": True,
        "company": normalized,
        "industry": company_overview.get("industry"),
        "health_score": (company_overview.get("health") or {}).get("score"),
        "coverage_pct": round(available_metrics / total_metrics * 100, 1),
        "available_metrics": available_metrics,
        "total_metrics": total_metrics,
        "risk_flag_count": len(risk_flags),
        "risk_flags": risk_flags[:6],
        "latest_period": latest_report.get("period_end"),
        "report_quality": latest_report.get("quality_score"),
        "source": "Indexed financial-statement library",
        "refresh_instruction": "Upload and re-index a newer statement, then rerun Indicators & VSA.",
    }


def _indicator_settings(body):
    return {
        "profile": body.get("profile", "balanced"),
        "account_value": body.get("account_value"),
        "risk_pct": body.get("risk_pct", 1.0),
        "position_status": body.get("position_status", "watching"),
        "entry_price": body.get("entry_price"),
        "sector_exposure_pct": body.get("sector_exposure_pct", 0.0),
    }


@app.post("/api/indicators-vsa/analyze")
def api_indicators_vsa_analyze():
    body = request.get_json(silent=True) or {}
    company = str(body.get("company") or "").strip().upper()[:80]
    if not company:
        return jsonify({"success": False, "error": "Enter a company or ticker.", "code": "invalid_company"}), 400
    data = analyze_vsa_company(
        company,
        market_symbol=str(body.get("market_symbol") or "").strip() or None,
        fundamental_context=_indicator_statement_context(company),
        **_indicator_settings(body),
    )
    return jsonify(data)


@app.post("/api/indicators-vsa/screen")
def api_indicators_vsa_screen():
    body = request.get_json(silent=True) or {}
    requested = body.get("companies")
    if isinstance(requested, str):
        requested = [item.strip() for item in requested.split(",") if item.strip()]
    if isinstance(requested, list) and requested:
        rows = []
        symbols = body.get("market_symbols") if isinstance(body.get("market_symbols"), dict) else {}
        for value in requested[:10]:
            company = str(value.get("company") if isinstance(value, dict) else value or "").strip().upper()[:80]
            if company:
                rows.append({
                    "company": company,
                    "market_symbol": (value.get("market_symbol") if isinstance(value, dict) else symbols.get(company)),
                    "fundamental_context": _indicator_statement_context(company),
                })
    else:
        rows = []
        for item in db.companies()[:10]:
            company = str(item.get("company") or "").strip().upper()
            rows.append({
                "company": company,
                "fundamental_context": _indicator_statement_context(company),
            })
    if not rows:
        return jsonify({
            "success": False,
            "error": "Add company reports or provide a comma-separated ticker universe first.",
            "code": "empty_universe",
        }), 400
    settings = _indicator_settings(body)
    settings.pop("position_status", None)
    settings.pop("entry_price", None)
    return jsonify(screen_vsa_companies(rows, **settings))


@app.get("/api/market-snapshot/<company>")
def api_market_snapshot(company):
    return jsonify(market_snapshot(company.upper()))


@app.post("/api/market-snapshots")
def api_market_snapshots():
    """Return several company snapshots through one bounded browser request."""
    body = request.get_json(silent=True) or {}
    requested = body.get("companies") if isinstance(body.get("companies"), list) else []
    companies = []
    for value in requested[:20]:
        company = str(value or "").strip().upper()[:80]
        if company and company not in companies:
            companies.append(company)
    if not companies:
        return jsonify({"success": False, "error": "Provide at least one company."}), 400
    snapshots = {}
    with ThreadPoolExecutor(max_workers=min(5, len(companies))) as pool:
        futures = {pool.submit(market_snapshot, company): company for company in companies}
        for future in as_completed(futures):
            company = futures[future]
            try:
                snapshots[company] = future.result()
            except Exception:
                snapshots[company] = {"success": False, "ticker": ticker_for(company), "error": "Market snapshot unavailable."}
    return jsonify({"success": True, "snapshots": snapshots, "request_strategy": "bounded server batch"})

@app.get("/api/world-markets")
def api_world_markets():
    mode = request.args.get("mode", "intraday")
    started=time.monotonic()
    data=world_market_snapshot(force=request.args.get("force") == "1", mode=mode)
    available=sum(1 for row in data.get("markets",[]) if row.get("latest") is not None or row.get("value") is not None)
    record_provider("Yahoo Finance","healthy" if available else "degraded",message=f"{available} market series returned in {mode} mode.",latency_ms=(time.monotonic()-started)*1000,cached=bool(data.get("cache_hit")),evidence_count=available)
    return jsonify(data)

@app.get("/api/macro")
def api_macro():
    started=time.monotonic()
    data=macro_snapshot(force=request.args.get("force") == "1")
    available=sum(1 for value in data.values() if isinstance(value,dict) and (value.get("latest") or value.get("points")))
    record_provider("Macro data","healthy" if available else "degraded",message=f"{available} macro datasets are currently available.",latency_ms=(time.monotonic()-started)*1000,evidence_count=available)
    return jsonify(data)

@app.get("/api/dashboard-macro")
def api_dashboard_macro():
    started = time.monotonic()
    data = dashboard_macro_snapshot(force=request.args.get("force") == "1")
    available = int(data.get("available_series") or 0)
    live = int(data.get("live_series") or 0)
    cached = int(data.get("snapshot_series") or 0)
    status = "healthy" if available == 5 and live == 5 else "degraded" if available else "unavailable"
    record_provider(
        "Macro data",
        status,
        message=f"{available} of 5 official dashboard macro series are available ({live} live, {cached} packaged snapshot).",
        latency_ms=(time.monotonic() - started) * 1000,
        evidence_count=available,
        cached=bool(cached),
    )
    return jsonify(data)

@app.get("/api/event-probability/options")
def api_event_probability_options():
    return jsonify({"success": True, "categories": catalog_options()})

@app.post("/api/event-probability/analyze")
def api_event_probability_analyze():
    body = request.get_json(silent=True) or {}
    category = str(body.get("category") or "").strip().lower()
    factor = str(body.get("factor") or "").strip().lower()
    focus = str(body.get("focus") or "").strip()
    horizon = str(body.get("horizon") or "30 days").strip()
    try:
        return jsonify(analyze_factor(category, factor, focus, horizon, **_forecast_scope()))
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@app.get("/api/event-probability/history")
def api_event_probability_history():
    try:
        limit=max(1,min(100,int(request.args.get("limit",30))))
    except (TypeError,ValueError):
        limit=30
    saved_only=request.args.get("saved") == "1"
    scope = _forecast_scope()
    return jsonify({
        "success": True,
        "forecasts": event_db.recent_forecasts(limit, saved_only=saved_only, **scope),
        "calibration": event_db.calibration_summary(**scope),
    })


@app.get("/api/event-probability/forecast/<int:forecast_id>")
def api_event_probability_forecast(forecast_id):
    row=event_db.get_forecast(forecast_id, **_forecast_scope())
    return (jsonify({"success":True,"forecast":row}) if row else (jsonify({"success":False,"error":"Forecast not found."}),404))


@app.post("/api/event-probability/review/<int:forecast_id>")
def api_event_probability_review(forecast_id):
    body=request.get_json(silent=True) or {}
    updates={key:body[key] for key in ("saved","note","resolved_outcome") if key in body}
    try:
        review=event_db.update_review(forecast_id, updates, **_forecast_scope())
    except ValueError as exc:
        return jsonify({"success":False,"error":str(exc)}),400
    if review is None:
        return jsonify({"success":False,"error":"Forecast not found."}),404
    return jsonify({"success": True, "review": review, "calibration": event_db.calibration_summary(**_forecast_scope())})


@app.get("/api/system-health")
def api_system_health():
    companies=db.companies()
    stats={"companies":len(companies),"reports":sum(int(row.get("reports") or 0) for row in companies)}
    data=provider_snapshot(stats)
    data["application"] = {
        "version": APP_VERSION,
        "startup": STARTUP_SCAN,
        "event_calibration": event_db.calibration_summary(**_forecast_scope()),
    }
    return jsonify(data)


@app.get("/api/market-news")
def api_market_news():
    started=time.monotonic()
    try:
        data=macro_news_search(limit=12)
        count=len(data.get("items",[])) if isinstance(data,dict) else 0
        record_provider("Market news","healthy" if count else "degraded",message=f"{count} market stories are available.",latency_ms=(time.monotonic()-started)*1000,evidence_count=count)
        return jsonify(data)
    except Exception:
        record_provider("Market news","unavailable",message="Market news is temporarily unavailable; other research features remain available.",latency_ms=(time.monotonic()-started)*1000,evidence_count=0)
        return jsonify({"success": False, "items": [], "error": "Market news is temporarily unavailable."}), 502


@app.get("/api/news")
def api_news():
    company = request.args.get("company", "").strip().upper()
    if not company:
        return jsonify({"success": False, "items": [], "error": "Company is required."}), 400
    try:
        return jsonify(news_search(company))
    except Exception as exc:
        return jsonify({"success": False, "items": [], "error": str(exc)}), 502


def _metric_value(item):
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get("value")
    return item

def _format_pct(value):
    return "Unavailable" if value is None else f"{float(value):.1f}%"

def _format_money(value):
    if value is None:
        return "Unavailable"
    n=float(value)
    a=abs(n)
    if a>=1e12: return f"{n/1e12:.3f}T VND"
    if a>=1e9: return f"{n/1e9:.3f}B VND"
    if a>=1e6: return f"{n/1e6:.1f}M VND"
    return f"{n:,.0f} VND"

def _resolve_question_companies(question, requested):
    found=[]
    for item in requested:
        raw=str(item or "").strip().upper()
        if raw and raw not in found:
            found.append(raw)
    library=db.companies()
    q=(question or "").strip().upper()
    # Match exact stored names, tickers, and market aliases embedded in the question.
    for row in library:
        stored=str(row.get("company") or "").strip().upper()
        aliases={stored, ticker_for(stored).replace(".VN", "")}
        for alias in list(aliases):
            if alias and alias in q and alias not in found:
                found.append(alias)
    return found

def _deterministic_answer(question, evidence):
    items=[x for x in evidence.get("companies",[]) if isinstance(x,dict) and not x.get("error")]
    q=(question or "").lower()
    if not items:
        return "I can help with your local financial library. Try: “Analyze FPT”, “What is FPT’s EBITDA margin?”, or “Compare FPT and CMG”."
    if "why is" in q and "unavailable" in q:
        x=items[0] if items else None
        if x:
            reasons=x.get("coverage",{}).get("unavailable_reasons",{})
            if reasons:
                detail="; ".join(f"{k.replace('_',' ')}: {v}" for k,v in reasons.items())
                return f"Here is why some metrics are unavailable for {x.get('company')}: {detail}"
    if "key risk" in q or "main risk" in q or "risk signals" in q:
        x=items[0] if items else None
        if x:
            try:
                r=assess(x.get('company'))
                flags=r.get('flags') or []
                return f"Risk review for {x.get('company')}: " + ("; ".join(flags) if flags else "no major rule-based warning in the currently verified data")
            except Exception:
                pass
    if "stop loss" in q or "stop-loss" in q or "position size" in q:
        x=items[0] if items else None
        if x:
            return f"Open Trade Planner for {x.get('company')}. It estimates historical downside, expectancy, a volatility/structure-based stop, and a risk-budget position size."
    if "research brief" in q or "research report" in q:
        x=items[0] if items else None
        if x:
            rb=research_brief(x.get('company'))
            m=rb.get('metrics',{})
            return f"Research brief for {x.get('company')}: revenue {_format_money(_metric_value(m.get('revenue')))}, net margin {_format_pct(_metric_value(m.get('net_margin')))}, EBITDA margin {_format_pct(_metric_value(m.get('ebitda_margin')))}, ROE {_format_pct(_metric_value(m.get('roe')))}, ROA {_format_pct(_metric_value(m.get('roa')))}."
    if len(items)>=2 or "compare" in q or " vs " in q:
        parts=[]
        for x in items:
            m=x.get("metrics",{})
            parts.append(f"{x.get('company')}: revenue {_format_money(_metric_value(m.get('revenue')))}, growth {_format_pct(m.get('revenue_growth'))}, net margin {_format_pct(_metric_value(m.get('net_margin')))}, EBITDA margin {_format_pct(_metric_value(m.get('ebitda_margin')))}, ROA {_format_pct(_metric_value(m.get('roa')))}, ROE {_format_pct(_metric_value(m.get('roe')))}.")
        return "Here is the comparison from the verified library evidence:\n\n" + "\n".join(parts)
    x=items[0]; m=x.get("metrics",{}); c=x.get("coverage",{}); lr=x.get("latest_report",{})
    answer=(f"Here is the latest verified view of {x.get('company')} ({x.get('industry','')}). "
            f"Revenue: {_format_money(_metric_value(m.get('revenue')))}; "
            f"revenue growth: {_format_pct(m.get('revenue_growth'))}; "
            f"net margin: {_format_pct(_metric_value(m.get('net_margin')))}; "
            f"EBITDA margin: {_format_pct(_metric_value(m.get('ebitda_margin')))}; "
            f"ROA: {_format_pct(_metric_value(m.get('roa')))}; "
            f"ROE: {_format_pct(_metric_value(m.get('roe')))}. ")
    if c.get("unavailable_reasons"):
        missing=[k.replace("_"," ") for k,v in c["unavailable_reasons"].items() if k and v]
        if missing:
            answer += "Unavailable metrics: " + ", ".join(missing) + ". "
    answer += f"Latest report period: {lr.get('period_end') or 'not detected'}."
    return answer

@app.post("/api/ask")
def api_ask():
    body = request.get_json(silent=True) or {}
    question = (body.get("question") or "").strip()
    requested = [str(x).strip() for x in body.get("companies", []) if str(x).strip()]
    if not question:
        return jsonify({"success": False, "error": "Question is required."}), 400
    q = question.lower()
    greetings = {"hi","hello","hey","xin chao","xin chào","good morning","good afternoon","good evening"}
    if q in greetings or any(q.startswith(g + " ") for g in greetings):
        return jsonify({"success": True, "answer": "Hello — I’m Financial AI. I can help you analyze a company, explain a financial metric, compare companies, review risk signals, or explore your report evidence.", "evidence": {"companies": []}})
    if q in {"help","what can you do","what can you help with","how can you help me"}:
        return jsonify({"success": True, "answer": "You can ask me things like: “Analyze FPT”, “What is FPT’s EBITDA margin?”, “Compare FPT and CMG”, “Why is a metric unavailable?”, or “Show me the main risk signals.” I use the evidence available in your local library for company-specific facts.", "evidence": {"companies": []}})
    companies=_resolve_question_companies(question, requested)
    # Backend-side extraction makes the assistant work even if the browser does not send an explicit company list.
    if not companies and len(q.split())==1:
        companies=_resolve_question_companies(q, [q.upper()])
    evidence = {"companies": [overview(company) for company in companies]}
    # Natural-language model is optional. Keep the assistant useful without Ollama.
    deterministic=_deterministic_answer(question, evidence)
    if evidence.get("companies"):
        try:
            answer=explain(question, evidence)
            if not answer or "currently unavailable" in answer.lower():
                answer=deterministic
        except Exception:
            answer=deterministic
    else:
        answer=deterministic
    return jsonify({"success": True, "answer": answer, "evidence": evidence})


@app.post("/api/scan")
def api_scan():
    if not _has_role("admin", "editor"):
        return _role_error("admin", "editor")
    job = jobs.submit("library_scan", scan, owner_user_id=g.current_user["id"])
    return jsonify({"success": True, "job": job}), 202


@app.get("/api/jobs/<job_id>")
def api_job(job_id):
    job = jobs.public_job(
        job_id,
        owner_user_id=g.current_user["id"],
        is_admin=_has_role("admin"),
    )
    if not job:
        return jsonify({"success": False, "error": "Job not found.", "code": "not_found"}), 404
    return jsonify({"success": True, "job": job})


@app.post("/api/upload")
def api_upload():
    if not _has_role("admin", "editor"):
        return _role_error("admin", "editor")
    if _UPLOAD_LIMITER.exceeded(
        "report_upload", g.current_user["id"], MAX_USER_UPLOADS_PER_HOUR, 3600
    ):
        return _rate_limit_response("Upload limit reached. Try again later.")
    uploaded = request.files.get("file")
    industry = (request.form.get("industry") or "").strip()
    company = (request.form.get("company") or "").strip().upper()
    if not uploaded or not industry or not company:
        return jsonify({"success": False, "error": "File, industry and company are required."}), 400

    try:
        industry = safe_path_segment(industry, "Industry")
        company = safe_path_segment(company, "Company")
        safe_name = safe_uploaded_name(uploaded, SUPPORTED_REPORT_TYPES, "report")
        suffix = Path(safe_name).suffix.lower()
        validate_upload_content(uploaded, suffix, max_pages=MAX_REPORT_PAGES)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    destination = REPORTS_DIR / industry / company / safe_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    quarantine = UPLOAD_DIR / ".quarantine"
    quarantine.mkdir(parents=True, exist_ok=True)
    temporary = quarantine / f"{secrets.token_hex(12)}-{safe_name}"
    try:
        uploaded.save(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    job = jobs.submit("library_scan", scan, owner_user_id=g.current_user["id"])
    return jsonify({
        "success": True,
        "saved_to": str(destination.relative_to(REPORTS_DIR)),
        "job": job,
    }), 202


@app.post("/api/chart")
def api_chart():
    if not _has_role("admin", "editor"):
        return _role_error("admin", "editor")
    if _UPLOAD_LIMITER.exceeded(
        "chart_upload", g.current_user["id"], MAX_USER_UPLOADS_PER_HOUR, 3600
    ):
        return _rate_limit_response("Upload limit reached. Try again later.")
    uploaded = request.files.get("file")
    company = (request.form.get("company") or "").strip().upper()
    if not uploaded or not company:
        return jsonify({"success": False, "error": "Image and company are required."}), 400
    try:
        company = safe_path_segment(company, "Company")
        safe_name = safe_uploaded_name(uploaded, {".png", ".jpg", ".jpeg", ".webp"}, "chart")
        suffix = Path(safe_name).suffix.lower()
        validate_upload_content(uploaded, suffix)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    destination = UPLOAD_DIR / f"{secrets.token_hex(6)}-{safe_name}"
    try:
        uploaded.save(destination)
        result = stock_analyze(company)
    finally:
        destination.unlink(missing_ok=True)
    result["note"] = "The chart image is supplementary evidence. The quantitative signal uses historical market data; it is not a guaranteed buy/sell instruction."
    return jsonify({"success": True, "result": result})


if __name__ == "__main__":
    print(f"Financial AI running on port {APP_PORT}")
    app.run(host=os.getenv("SOLVAI_HOST", "0.0.0.0"), port=APP_PORT, debug=False)
