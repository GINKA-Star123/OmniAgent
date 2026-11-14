from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from aiagent.state.private_resources import PRIVATE_AUDIO_ROOT, get_private_resources
from apps.api.shared_state_errors import shared_state_error_response

router = APIRouter()


@router.get("/audio/{filename}")
def get_audio(filename: str, request: Request):
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(401, detail={"code": "authentication_required"})
    if Path(filename).name != filename or "\\" in filename or "%" in filename:
        raise HTTPException(404, detail={"code": "audio_not_found"})
    try:
        resource = get_private_resources().owned("audio", filename, principal.user_id)
    except Exception as exc:
        response = shared_state_error_response(exc)
        if response is not None:
            return response
        raise
    if resource is None:
        raise HTTPException(404, detail={"code": "audio_not_found"})
    path = Path(resource.get("path", "")).resolve()
    if (not path.is_relative_to(PRIVATE_AUDIO_ROOT) or path.name != filename
            or not path.is_file() or path.suffix.lower() not in {".wav", ".mp3", ".ogg"}):
        raise HTTPException(404, detail={"code": "audio_not_found"})
    media_type = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg"}[path.suffix.lower()]
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
