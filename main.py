from fastapi import FastAPI, Request
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

from database import supabase
from webhook import verify_webhook, receive_webhook

app = FastAPI(title="WaveMatch API", version="0.1.0")

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