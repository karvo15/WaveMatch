"""
Conversation state management for WaveMatch.
Provides shared functions for getting, setting, and clearing conversation states
in the Supabase database.
"""

import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import anyio
from dotenv import load_dotenv
from database import supabase

# Load environment variables
load_dotenv()

# Semaphore to limit concurrent DB operations and prevent HTTP/2 connection overload
_db_semaphore = asyncio.Semaphore(10)  # Allow up to 10 concurrent DB operations


async def get_conversation_state(phone_number: str) -> Optional[Dict]:
    """
    Get conversation state for a phone number.

    Args:
        phone_number: The phone number in international format

    Returns:
        Dict with keys: phone_number, current_flow, current_step, collected_data if row exists
        None if no conversation state row exists for the phone number
    """
    def _get():
        result = supabase.from_("conversation_states").select("*").eq("phone_number", phone_number).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]
        return None

    async with _db_semaphore:  # Limit concurrent DB access
        return await anyio.to_thread.run_sync(_get)


async def set_conversation_state(phone_number: str, flow: str, step: str, data: Dict[str, Any]) -> None:
    """
    Set conversation state for a phone number with Python-side JSONB merge (MVP tradeoff).

    Args:
        phone_number: The phone number in international format
        flow: The current flow identifier (e.g., 'register_user', 'register_poster')
        step: The current step identifier (e.g., 'awaiting_interests', 'awaiting_display_name')
        data: Dictionary of data to merge into collected_data
    """
    def _set():
        # Get existing data to merge (Python-side merge accepted as MVP tradeoff)
        existing_result = supabase.from_("conversation_states").select("collected_data").eq("phone_number", phone_number).execute()

        # Merge data in Python - ACCEPTED TRADEOFF FOR MVP
        if existing_result.data and len(existing_result.data) > 0:
            existing_data = existing_result.data[0].get("collected_data", {})
            merged_data = {**existing_data, **data} if isinstance(existing_data, dict) else data
        else:
            merged_data = data

        # Upsert with explicit conflict target and updated_at
        result = supabase.from_("conversation_states").upsert({
            "phone_number": phone_number,
            "current_flow": flow,
            "current_step": step,
            "collected_data": merged_data,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, on_conflict="phone_number").execute()

        return result

    async with _db_semaphore:  # Limit concurrent DB access
        await anyio.to_thread.run_sync(_set)


async def clear_conversation_state(phone_number: str) -> None:
    """
    Clear conversation state for a phone number.

    Args:
        phone_number: The phone number in international format
    """
    def _clear():
        return supabase.from_("conversation_states").delete().eq("phone_number", phone_number).execute()

    async with _db_semaphore:  # Limit concurrent DB access
        await anyio.to_thread.run_sync(_clear)


async def user_exists(phone_number: str) -> bool:
    """
    Check if a user exists with the given phone number.

    Args:
        phone_number: The phone number in international format

    Returns:
        True if user exists, False otherwise
    """
    def _check():
        result = supabase.from_("users").select("id").eq("phone_number", phone_number).execute()
        return bool(result.data and len(result.data) > 0)

    async with _db_semaphore:  # Limit concurrent DB access
        return await anyio.to_thread.run_sync(_check)


async def poster_exists(phone_number: str) -> bool:
    """
    Check if a poster exists with the given phone number.

    Args:
        phone_number: The phone number in international format

    Returns:
        True if poster exists, False otherwise
    """
    def _check():
        result = supabase.from_("posters").select("id").eq("phone_number", phone_number).execute()
        return bool(result.data and len(result.data) > 0)

    async with _db_semaphore:  # Limit concurrent DB access
        return await anyio.to_thread.run_sync(_check)
