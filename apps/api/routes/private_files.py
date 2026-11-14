from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from cloud.config import cloud_settings

router = APIRouter()

@router.get("/cloud-files/{key:path}")
def private_cloud_file(key: str):
    if cloud_settings.storage_provider.lower() != "local":
        raise HTTPException(404, detail="not_found")
    root = Path(cloud_settings.local_storage_root).resolve()
    if not key or "\\" in key or "%" in key:
        raise HTTPException(404, detail="not_found")
    path = (root / key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404, detail="not_found")
    return FileResponse(path, headers={"Cache-Control": "private, no-store",
                                       "X-Content-Type-Options": "nosniff"})
