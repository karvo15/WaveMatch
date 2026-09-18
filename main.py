import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

from database import supabase
from scheduler import (
    check_exact_reminder_schema,
    run_catchup_daily_scheduler,
    run_exact_reminder_pass,
    start_scheduler,
)
from webhook import verify_webhook, receive_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the scheduler with the app and stop it on shutdown.

    2-Architecture-Doc.md Section 3C, option 2: the in-process APScheduler jobs are now
    only one of *two* drivers. A Render Cron Job calls POST /internal/run-scheduler, and
    both drivers go through scheduler.run_catchup_daily_scheduler(), whose `scheduler_runs`
    marker decides who does the day's work. That matters because this process does not stay
    awake -- the free tier spins it down after 15 idle minutes, which is exactly how a day's
    reminders were being lost -- and the endpoint wakes it back up to serve the cron request.

    On startup we also run one catch-up: if the service slept through the scheduled hour,
    today's pass still happens on the first wake-up instead of silently skipping the day.
    Fire-and-forget, so a slow pass never delays the app becoming ready, and marker-guarded,
    so it can never double up with the cron.
    """
    # Loud, never fatal: a deploy that ships ahead of the migration should say so here
    # rather than look like "reminders silently stopped working" later.
    try:
        await check_exact_reminder_schema()
    except Exception:
        logger.exception("SCHEMA_CHECK_FAILED")

    scheduler = start_scheduler()
    if scheduler:
        for job in scheduler.get_jobs():
            logger.info(f"SCHEDULER_JOB_REGISTERED: id={job.id} next_run={job.next_run_time}")

    async def _startup_catchup() -> None:
        try:
            await run_catchup_daily_scheduler()
        except Exception:
            logger.exception("STARTUP_CATCHUP_FAILED")

    asyncio.create_task(_startup_catchup())

    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)
            logger.info("SCHEDULER_SHUTDOWN")


app = FastAPI(title="WaveMatch API", version="0.1.0", lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "WaveMatch is running"}

@app.get("/health")
async def health_check_detailed():
    return {
        "status": "healthy",
        "timestamp": os.times().elapsed,
        "version": "0.1.0"
    }

@app.get("/db-test")
async def test_db():
    try:
        result = supabase.from_("tags").select("*").limit(1).execute()
        return {"status": "success", "data": result.data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Webhook endpoints for WhatsApp Cloud API
@app.get("/webhook")
async def webhook_verification(request: Request):
    return await verify_webhook(request)

@app.post("/webhook")
async def webhook_receiver(request: Request):
    return await receive_webhook(request)


# ============================================================
# INTERNAL SCHEDULER TICK (2-Architecture-Doc.md Section 3C, option 2)
# ============================================================
# Called by a Render Cron Job every few minutes. This exists because the in-process
# APScheduler jobs only run while the service is awake, and Render's free tier spins an
# idle service down -- which is how a user's "remind me in 1 hour" was lost.
#
# The request also *wakes* the service, so this works from cold.
#
# Protected by a shared secret: without it, this route would be a public way to make the
# bot message people. Set INTERNAL_TICK_SECRET in the Render environment; an unset secret
# disables the route rather than leaving it open.
INTERNAL_TICK_SECRET = os.getenv("INTERNAL_TICK_SECRET", "").strip()
INTERNAL_TICK_HEADER = "x-tick-secret"


@app.post("/internal/run-scheduler")
async def run_scheduler_tick(request: Request):
    if not INTERNAL_TICK_SECRET:
        logger.warning("INTERNAL_TICK_DISABLED: INTERNAL_TICK_SECRET is not set")
        return JSONResponse(
            {"status": "disabled", "detail": "INTERNAL_TICK_SECRET is not set"},
            status_code=503,
        )

    provided = request.headers.get(INTERNAL_TICK_HEADER, "")
    if not hmac.compare_digest(provided, INTERNAL_TICK_SECRET):
        logger.warning("INTERNAL_TICK_UNAUTHORIZED: rejected a request with a bad or missing secret")
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    # Exact-time reminders first: those are the ones a user is waiting on to the minute.
    exact_sent = await run_exact_reminder_pass()
    daily = await run_catchup_daily_scheduler()

    logger.info(
        f"INTERNAL_TICK_DONE: exact_reminders_sent={exact_sent} "
        f"daily_pass={'ran' if daily else 'skipped'}"
    )
    return {
        "status": "ok",
        "exact_reminders_sent": exact_sent,
        "daily_pass_ran": bool(daily),
        "daily_pass_summary": daily,
    }