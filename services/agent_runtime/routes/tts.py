"""Voice replies: proxy to an OpenAI-compatible speech endpoint.

The browser talks to this same-origin route instead of the TTS host directly,
so the SPA needs no CORS grant and the synthesizer URL stays server-side.
Kokoro (microbalance-tts) exposes exactly ``POST /v1/audio/speech`` and returns
``audio/wav``.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from flare_common.config import Settings

logger = logging.getLogger(__name__)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None


def build_tts_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["speech"])

    @router.post("/tts")
    async def synthesize(payload: SpeechRequest) -> Response:
        if not settings.tts_enabled:
            raise HTTPException(
                status_code=503,
                detail={"code": "TTS_DISABLED", "message": "Voice replies are disabled."},
            )
        text = payload.text.strip()
        if text == "":
            raise HTTPException(
                status_code=422,
                detail={"code": "TTS_EMPTY", "message": "Text is required."},
            )
        body = {
            "input": text,
            "voice": payload.voice or settings.tts_voice,
            "speed": settings.tts_speed,
        }
        try:
            async with httpx.AsyncClient(timeout=settings.tts_timeout) as client:
                upstream = await client.post(settings.tts_url, json=body)
        except httpx.HTTPError as exc:
            logger.warning("tts upstream unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "TTS_UNAVAILABLE",
                    "message": "The voice service is not running.",
                },
            ) from exc
        if upstream.status_code != 200:
            logger.warning("tts upstream error %s: %s", upstream.status_code, upstream.text[:200])
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "TTS_UPSTREAM",
                    "message": "The voice service could not synthesize this reply.",
                },
            )
        return Response(
            content=upstream.content,
            media_type="audio/wav",
            headers={"Cache-Control": "no-store"},
        )

    return router
