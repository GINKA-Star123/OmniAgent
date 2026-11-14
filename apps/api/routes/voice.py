from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from apps.api.response_utils import error_response, ok_response
from apps.core.runtime_registry import get_runtime, get_runtime_error
from cloud.config import cloud_settings

router = APIRouter()
logger = logging.getLogger("aiagent.api.voice")


class VoiceTurnRequest(BaseModel):
    user_id: str = "mic"
    username: str = "麦克风输入"
    max_seconds: float = 8.0
    silence_seconds: float = 1.2
    interrupt_playback: bool = True


class InterruptRequest(BaseModel):
    reason: str = "api_interrupt"


def _runtime_or_error(route_name:str):
    try:
        return get_runtime(),None
    except Exception as exc:
        logger.exception("Runtime init failed in %s: %s", route_name, exc)
        return None,error_response(
            stage = "runtime_init",
            exc = exc,
            status_code = 500,
            runtime_error = get_runtime_error(),
            extra = {
                "route":route_name
            }
        )



@router.post("/voice/transcribe")
async def transcribe_voice(file: UploadFile = File(...)):
    runtime, failure = _runtime_or_error("/voice/transcribe")
    if failure is not None:
        return failure
    directory = Path("data/cache/private_asr")
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.wav").suffix.lower()
    if suffix not in {".wav", ".mp3", ".ogg", ".m4a", ".webm"}:
        return error_response(stage="voice_upload", exc=ValueError("audio_type_invalid"), status_code=400)
    path = directory / f"{uuid4().hex}{suffix}"
    try:
        total = 0
        with path.open("xb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > cloud_settings.upload_max_bytes:
                    return error_response(stage="voice_upload", exc=ValueError("audio_too_large"), status_code=413)
                handle.write(chunk)
        if total == 0:
            return error_response(stage="voice_upload", exc=ValueError("audio_empty"), status_code=400)
        transcript = await asyncio.to_thread(runtime.transcribe_audio_file, str(path))
        return ok_response(transcript=transcript)
    except Exception:
        return error_response(stage="voice_transcribe", exc=RuntimeError("transcription_failed"), status_code=503)
    finally:
        path.unlink(missing_ok=True)
        await file.close()

@router.post("/voice/turn")
def voice_turn(req: VoiceTurnRequest):
    runtime, error_response_value = _runtime_or_error("/voice/turn")
    if error_response_value is not None:
        return error_response_value

    try:
        output = runtime.handle_voice_turn(
            user_id=req.user_id,
            username=req.username,
            max_seconds=req.max_seconds,
            silence_seconds=req.silence_seconds,
            interrupt_playback=req.interrupt_playback,
        )

        packet = output.packet

        return ok_response(
            output_id=output.output_id,
            reply=packet.reply_text,
            base_reply_text=packet.base_reply_text,
            emotion=packet.emotion,
            motion=packet.motion,
            expression=packet.expression,
            audio_path=packet.audio_path,
            audio_url=packet.audio_url,
            audio_segments=packet.audio_segments,
            audio_segment_urls=packet.audio_segment_urls,
            audio_segment_texts=packet.audio_segment_texts,
            live2d_command_path=packet.live2d_command_path,
            live2d=packet.live2d,
            metadata=packet.metadata,
            stream_state=runtime.get_stream_state().model_dump(),
            speaking_state=runtime.get_speaking_state().model_dump(),
        )

    except Exception as exc:
        logger.exception("/voice/turn failed: %s", exc)
        return error_response(
            stage="voice_turn",
            exc=exc,
            status_code=500,
        )

@router.post("/voice/interrupt")
def interrupt_voice(req: InterruptRequest):
    runtime, error_response_value = _runtime_or_error("/voice/interrupt")
    if error_response_value is not None:
        return error_response_value

    try:
        result = runtime.interrupt_speaking(reason=req.reason)
        return ok_response(
            result=result,
            speaking_state=runtime.get_speaking_state().model_dump(),
        )

    except Exception as exc:
        logger.exception("/voice/interrupt failed: %s", exc)
        return error_response(
            stage="voice_interrupt",
            exc=exc,
            status_code=500,
        )


@router.get("/voice/state")
def voice_state():
    runtime, error_response_value = _runtime_or_error("/voice/state")
    if error_response_value is not None:
        return error_response_value

    try:
        current_audio_queue = (
            runtime.voice_session_controller.audio_playback_dispatcher.audio_player.get_current_playlist()
            if runtime.voice_session_controller is not None
            else []
        )

        return ok_response(
            stream_state=runtime.get_stream_state().model_dump(),
            speaking_state=runtime.get_speaking_state().model_dump(),
            current_audio_queue=current_audio_queue,
        )

    except Exception as exc:
        logger.exception("/voice/state failed: %s", exc)
        return error_response(
            stage="voice_state",
            exc=exc,
            status_code=500,
        )
