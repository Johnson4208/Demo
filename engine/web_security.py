"""Small web-input helpers kept independent from application startup."""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from threading import Lock
from zipfile import BadZipFile, ZipFile

from werkzeug.utils import secure_filename


def safe_path_segment(value, label):
    cleaned = " ".join(str(value or "").strip().split())
    if (
        not cleaned
        or cleaned in {".", ".."}
        or len(cleaned) > 100
        or any(character in cleaned for character in ("/", "\\", "\x00"))
        or any(ord(character) < 32 for character in cleaned)
    ):
        raise ValueError(f"{label} contains unsupported characters.")
    return cleaned


def safe_uploaded_name(uploaded, allowed_suffixes, fallback_stem):
    original = str(uploaded.filename or "").strip()
    suffix = Path(original.replace("\\", "/")).suffix.lower()
    if suffix not in allowed_suffixes:
        supported = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Unsupported file type. Use one of: {supported}.")
    safe = secure_filename(Path(original.replace("\\", "/")).name)
    return safe or f"{fallback_stem}{suffix}"


def validate_upload_content(uploaded, suffix, *, max_pages=500):
    """Reject extension spoofing and unsafe document structures before saving."""
    suffix = str(suffix or "").lower()
    stream = uploaded.stream
    position = stream.tell()
    header = stream.read(16)
    stream.seek(position)
    if suffix == ".pdf":
        if not header.startswith(b"%PDF-"):
            raise ValueError("The uploaded file does not contain a valid PDF signature.")
        try:
            from pypdf import PdfReader
            reader = PdfReader(stream, strict=False)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported.")
            if len(reader.pages) > int(max_pages):
                raise ValueError(f"PDF exceeds the {int(max_pages)} page processing limit.")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("The PDF structure could not be validated.") from exc
        finally:
            stream.seek(position)
    elif suffix == ".docx":
        if not header.startswith(b"PK"):
            raise ValueError("The uploaded file does not contain a valid DOCX signature.")
        try:
            with ZipFile(stream) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or not any(name.startswith("word/") for name in names):
                    raise ValueError("The uploaded archive is not a valid DOCX document.")
                if sum(max(0, item.file_size) for item in archive.infolist()) > 250 * 1024 * 1024:
                    raise ValueError("The expanded DOCX content is too large to process safely.")
        except ValueError:
            raise
        except BadZipFile as exc:
            raise ValueError("The DOCX structure could not be validated.") from exc
        finally:
            stream.seek(position)
    elif suffix in {".txt", ".md", ".csv"}:
        sample = stream.read(8192)
        stream.seek(position)
        if b"\x00" in sample:
            raise ValueError("Text reports cannot contain binary data.")
    elif suffix == ".png" and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The uploaded image is not a valid PNG file.")
    elif suffix in {".jpg", ".jpeg"} and not header.startswith(b"\xff\xd8\xff"):
        raise ValueError("The uploaded image is not a valid JPEG file.")
    elif suffix == ".webp" and not (header.startswith(b"RIFF") and header[8:12] == b"WEBP"):
        raise ValueError("The uploaded image is not a valid WebP file.")
    return True


class SlidingWindowLimiter:
    """Thread-safe, bounded limiter for a single application instance."""

    def __init__(self, max_clients=1000):
        self.max_clients = max(10, int(max_clients))
        self._lock = Lock()
        self._buckets = {}

    def exceeded(self, scope, identity, limit, window_seconds, *, now=None):
        timestamp = time.monotonic() if now is None else float(now)
        key = (str(scope), str(identity or "unknown"))
        limit = max(1, int(limit))
        window_seconds = max(1, int(window_seconds))
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            cutoff = timestamp - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return True
            bucket.append(timestamp)
            if len(self._buckets) > self.max_clients:
                for old_key, old_bucket in list(self._buckets.items()):
                    if not old_bucket or old_bucket[-1] <= cutoff:
                        self._buckets.pop(old_key, None)
            return False

    def clear(self):
        with self._lock:
            self._buckets.clear()
