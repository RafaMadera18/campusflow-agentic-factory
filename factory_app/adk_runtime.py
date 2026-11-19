"""Calls one ADK agent and returns its final text.

This is the only place where the planning runner touches a real model. Every call uses a
brand-new session, so agents never share conversation history: each one only sees the
prompt and the session state it is given.
"""

from __future__ import annotations

import asyncio

from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from .retry import call_with_retries

APP_NAME = "factory_app"
USER_ID = "factory"


def make_agent_fn(agent: LlmAgent):
    """Wrap an ADK agent as ``fn(prompt, session_state) -> text`` with retries on 429/503."""

    def ask(prompt: str, state: dict) -> str:
        return call_with_retries(lambda: asyncio.run(_ask_once(agent, prompt, state)))

    return ask


async def _ask_once(agent: LlmAgent, prompt: str, state: dict) -> str:
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, state=state
    )
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(part.text or "" for part in event.content.parts)
    return final_text
