from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from PIL import Image

from aiagent.vision.gif_frames import GifInfo, ImageInputError, inspect_gif

DEFAULT_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_EXTENSION_FORMATS = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF",
}

# 魔数签名 -> 规范格式名。用文件头判断真实类型，而不是相信后缀，
# 防止把 zip/pdf 改名成 .png 混进视觉链路。
_MAGIC_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
)

_HEADER_BYTES = 16


@dataclass(frozen=True)
class StoredImage:
    image_id: str
    path: Path
    sha256: str
    width: int
    height: int
    format: str
    gif_info: GifInfo | None = None


class ImageStore:
    def __init__(
        self,
        upload_dir: str | Path = "data/uploads/images",
        max_bytes: int = 12 * 1024 * 1024,
        allowed_extensions: set[str] | None = None,
        min_bytes: int = 64,
        max_pixels: int = 40_000_000,
    ) -> None:
        self.upload_dir = Path(upload_dir)
        self.max_bytes = max(int(max_bytes), 1)
        self.min_bytes = max(int(min_bytes), 0)
        # 解压炸弹防护：单张图最大像素数（4000 万像素约等于 8000x5000）。
        self.max_pixels = max(int(max_pixels), 1)
        self.allowed_extensions = allowed_extensions or set(DEFAULT_ALLOWED_EXTENSIONS)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, file_obj, filename: str) -> StoredImage:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in self.allowed_extensions:
            raise ImageInputError(f"Unsupported image extension: {suffix}")

        image_id = f"img_{uuid4().hex}"
        target_path = self.upload_dir / f"{image_id}{suffix}"

        hasher = hashlib.sha256()
        total = 0

        try:
            with target_path.open("wb") as output:
                while True:
                    chunk = file_obj.read(1024 * 1024)
                    if not chunk:
                        break

                    total += len(chunk)
                    if total > self.max_bytes:
                        raise ImageInputError(f"Image is too large. Max bytes: {self.max_bytes}")

                    hasher.update(chunk)
                    output.write(chunk)

            if total < self.min_bytes:
                raise ImageInputError(f"Image is too small or empty. Min bytes: {self.min_bytes}")

            return self._validate_and_describe(
                image_id=image_id,
                path=target_path,
                sha256=hasher.hexdigest(),
            )
        except Exception:
            target_path.unlink(missing_ok=True)
            raise

    def save_local_copy(self, source_path: str | Path) -> StoredImage:
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Image file not found: {source}")

        suffix = source.suffix.lower()
        if suffix not in self.allowed_extensions:
            raise ImageInputError(f"Unsupported image extension: {suffix}")

        # 先看体积再拷贝：原来的 read_bytes() 会在超大本地文件上瞬间吃光内存。
        size = source.stat().st_size
        if size > self.max_bytes:
            raise ImageInputError(f"Image is too large. Max bytes: {self.max_bytes}")
        if size < self.min_bytes:
            raise ImageInputError(f"Image is too small or empty. Min bytes: {self.min_bytes}")

        image_id = f"img_{uuid4().hex}"
        target_path = self.upload_dir / f"{image_id}{suffix}"

        try:
            shutil.copyfile(source, target_path)
            sha256 = _sha256_of_file(target_path)
            return self._validate_and_describe(
                image_id=image_id,
                path=target_path,
                sha256=sha256,
            )
        except Exception:
            target_path.unlink(missing_ok=True)
            raise

    def _validate_and_describe(self, image_id: str, path: Path, sha256: str) -> StoredImage:
        try:
            sniffed = sniff_image_format(path)
            if sniffed is None:
                raise ImageInputError("image_invalid_signature")
            if _EXTENSION_FORMATS.get(path.suffix.lower()) != sniffed:
                raise ImageInputError("image_extension_signature_mismatch")

            gif_info = None
            if sniffed == "GIF":
                gif_info = inspect_gif(path)
                width, height = gif_info.width, gif_info.height
                image_format = "GIF"
            else:
                with Image.open(path) as image:
                    if image.width * image.height > self.max_pixels:
                        raise ImageInputError("image_pixels_exceeded")
                    image.verify()

                with Image.open(path) as image:
                    width, height = image.size
                    image_format = (image.format or path.suffix.lstrip(".")).upper()

            if width <= 0 or height <= 0:
                raise ImageInputError("image_invalid_dimensions")

            if width * height > self.max_pixels:
                raise ImageInputError("image_pixels_exceeded")

            if image_format != sniffed:
                raise ImageInputError("image_decoded_format_mismatch")
        except ImageInputError:
            path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            path.unlink(missing_ok=True)
            raise ImageInputError("image_decode_failed") from exc

        return StoredImage(
            image_id=image_id,
            path=path,
            sha256=sha256,
            width=width,
            height=height,
            format=image_format,
            gif_info=gif_info,
        )


def sniff_image_format(path: str | Path) -> str | None:
    """用文件头判断真实图片格式，而不是相信后缀。"""
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(_HEADER_BYTES)
    except OSError:
        return None

    for signature, name in _MAGIC_SIGNATURES:
        if header.startswith(signature):
            return name

    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "WEBP"

    return None


def _sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
