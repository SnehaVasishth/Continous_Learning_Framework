import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import kb as _kb
from .config import APP_CORS_ORIGINS, OUTPUTS, ROOT, UPLOADS
from .db import Base, SessionLocal, engine
from .db_migrate import apply_lightweight_migrations
from .logging_setup import configure_logging
from .middleware.auth import BearerAuthMiddleware
from .middleware.basic_auth import BasicAuthMiddleware
from .routes import aioa as aioa_routes
from .routes import analytics, data, docs, email_accounts, emails, feedback, governance, hitl, integrations, kb, learning, notifications, pipeline, seed, sf_users, signal_graph, system, threads, trace
# === v1.1 TASK-7 START ===
from .routes import test_corpus
# === v1.1 TASK-7 END ===
from .services import aioa_service
from .services import connection_monitor
from .services import email_hitl_reconcile
from .services import email_sweeper
from .services import email_sync
from .services import pipeline_recovery
from .services import salesforce as sf_service
from .services import servicenow as sn_service
from .services import tunnel as tunnel_service

configure_logging()

# repo-root/frontend/dist (works in both local dev and the Docker image layout).
FRONTEND_DIST = ROOT.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio as _asyncio
    from .tracing import bus as _bus
    _bus.attach_loop(_asyncio.get_running_loop())
    Base.metadata.create_all(bind=engine)
    apply_lightweight_migrations(engine)
    db = SessionLocal()
    try:
        _kb.seed_defaults(db)
        from .services import baselines as _baselines_svc
        _baselines_svc.seed_defaults(db)
        # Concept-baseline consolidation: collapse any legacy per-segment
        # rows into the concept baseline for the same metric and re-stamp
        # the dependent signal anchors. Idempotent: when all rows are
        # already at segment="global" this is a no-op.
        try:
            _baselines_svc.consolidate_to_concept_baselines(db)
        except Exception:
            db.rollback()
        # Anchor every legacy Continuous-Learning signal to a baseline id
        # via (metric, segment) match. Idempotent: only fills NULL rows.
        try:
            _baselines_svc.backfill_baseline_ids(db)
        except Exception:
            # Backfill failures must never block boot. The detector will
            # stamp new signals correctly even if legacy backfill skips.
            db.rollback()
        # Reconcile the DriftAlert ledger against current Baseline state so
        # any seeded baseline that landed in `breached` surfaces in the
        # Overview tile and Drift tab immediately on boot, and any baseline
        # that recovered while the service was down has its open alerts
        # auto-resolved. Idempotent.
        try:
            from .services.monitor import ensure_drift_for_breached_baselines as _ensure_drift
            _ensure_drift(db)
        except Exception:
            db.rollback()
        pipeline_recovery.sweep_zombies(db)
        # Drain stale, never-triaged inbox so the Dashboard "New" tile
        # reflects work the operator can still act on. Older untouched
        # mail is reclassified to ``expired_unworkable`` (idempotent;
        # safe to run on every boot).
        try:
            email_sweeper.sweep_stale_new(db)
        except Exception:
            db.rollback()
        # Reconcile any Email rows stuck at awaiting_hitl whose HitlTask
        # was already resolved (or never existed). Idempotent; runs again
        # on every email poller tick via email_sync._tick.
        try:
            email_hitl_reconcile.reconcile_awaiting_hitl(db)
        except Exception:
            db.rollback()
    finally:
        db.close()
    if not (os.environ.get("APP_BASE_URL") or "").strip():
        tunnel_service.start(port=8000)
    if os.environ.get("EMAIL_SYNC_ENABLED", "1") != "0":
        email_sync.start()
    if os.environ.get("CONNECTION_MONITOR_ENABLED", "1") != "0":
        connection_monitor.start()
    if os.environ.get("AIOA_SERVICE_ENABLED", "1") != "0":
        aioa_service.start()
    if os.environ.get("REALISED_LIFT_WATCHER_ENABLED", "1") != "0":
        from .services.realised_lift_watcher import start_in_background as _start_rlw
        _start_rlw()
    # Continuous-Learning scheduler: drift detectors + candidate generators
    # tick periodically so "Continuous Learning" runs continuously, not just
    # on Refresh clicks. Toggle with CL_SCHEDULER_ENABLED=0 if needed.
    from .services.cl_scheduler import start_in_background as _start_cls
    _start_cls()
    try:
        yield
    finally:
        aioa_service.stop()
        await connection_monitor.stop()
        await email_sync.stop()
        tunnel_service.stop()


app = FastAPI(title="Keysight SalesOps Demo", lifespan=lifespan)

# BasicAuth wraps EVERYTHING (SPA + API + static) when APP_BASIC_AUTH_USER /
# APP_BASIC_AUTH_PASS are both set. Goes outermost so even the SPA index gates.
app.add_middleware(BasicAuthMiddleware)
app.add_middleware(BearerAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files/uploads", StaticFiles(directory=str(UPLOADS)), name="uploads")
app.mount("/files/outputs", StaticFiles(directory=str(OUTPUTS)), name="outputs")

app.include_router(emails.router, prefix="/api/emails", tags=["emails"])
app.include_router(pipeline.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(threads.router, prefix="/api/threads", tags=["threads"])
app.include_router(hitl.router, prefix="/api/hitl", tags=["hitl"])
app.include_router(trace.router, prefix="/api/trace", tags=["trace"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(seed.router, prefix="/api/seed", tags=["seed"])
app.include_router(data.router, prefix="/api/data", tags=["data"])
app.include_router(docs.router, prefix="/api/docs", tags=["docs"])
app.include_router(kb.router, prefix="/api/kb", tags=["kb"])
app.include_router(email_accounts.router, prefix="/api/email-accounts", tags=["email-accounts"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
app.include_router(system.router, prefix="/api/system", tags=["system"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(learning.router, prefix="/api/learning", tags=["learning"])
app.include_router(sf_users.router, prefix="/api/sf-users", tags=["sf-users"])
app.include_router(governance.router, prefix="/api/governance", tags=["governance"])
app.include_router(aioa_routes.router, prefix="/api/aioa", tags=["aioa"])
# === v1.1 TASK-7 ===
app.include_router(test_corpus.router, prefix="/api/test-corpus", tags=["test-corpus"])
app.include_router(signal_graph.router, prefix="/api/signal-graph", tags=["signal-graph"])


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/ready")
def ready():
    db_status = "down"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "down"

    sf_status = "not_configured"
    sn_status = "not_configured"
    db = SessionLocal()
    try:
        if sf_service.get_active_connection(db) is not None:
            sf_status = "connected"
        if sn_service.get_active_connection(db) is not None:
            sn_status = "connected"
    except Exception:
        pass
    finally:
        db.close()

    outbound_email_enabled = (os.environ.get("OUTBOUND_EMAIL_ENABLED", "1").strip() or "1") != "0"
    return {
        "db": db_status,
        "salesforce": sf_status,
        "servicenow": sn_status,
        "outbound_email_enabled": outbound_email_enabled,
        "ready": db_status == "ok",
    }


# Static SPA mount must come AFTER /api/* routes so they take precedence.
if (FRONTEND_DIST / "index.html").exists():
    _index = FRONTEND_DIST / "index.html"

    @app.get("/{path:path}")
    def _spa(path: str):
        if path.startswith("api/") or path.startswith("files/"):
            return JSONResponse(status_code=404, content={"error": "not_found"})
        candidate = FRONTEND_DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_index)

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="spa")
