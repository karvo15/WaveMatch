import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

from database import supabase
from scheduler import start_scheduler
from webhook import verify_webhook, receive_webhook

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the Phase L daily scheduler with the app and stop it on shutdown.

    Deliberate choice per 2-Architecture-Doc.md Section 3C: an in-process
    APScheduler job, NOT a Render Cron Job. It therefore only runs while the
    service is awake -- the accepted MVP tradeoff. `scheduler.run_daily_scheduler()`
    stays a plain callable, so the exact same passes can be run on demand if a day
    is ever skipped during a long idle stretch on the free tier.
    """
    scheduler = start_scheduler()
    if scheduler:
        for job in scheduler.get_jobs():
            logger.info(f"SCHEDULER_JOB_REGISTERED: id={job.id} next_run={job.next_run_time}")
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