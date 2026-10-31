"""Bounded input handling without importing submitted Python."""

import io
import re
import tokenize

MAX_BYTES = 50_000


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)[:100]
    if not name.lower().endswith(".py"):
        raise ValueError("Only Python .py files are supported.")
    return name


def validate_source(code: str) -> str:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Enter a non-empty Python source file.")
    try:
        size = len(code.encode("utf-8"))
    except UnicodeError as error:
        raise ValueError("Source contains invalid Unicode.") from error
    if size > MAX_BYTES:
        raise ValueError("Input exceeds the 50 KB UTF-8 limit.")
    if "\x00" in code:
        raise ValueError("Source contains a null byte.")
    return code


def decode_upload(name: str, data: bytes) -> tuple[str, str]:
    filename = safe_filename(name)
    if len(data) > MAX_BYTES:
        raise ValueError("Uploaded file exceeds the 50 KB limit.")
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        code = data.decode(encoding)
    except (UnicodeError, LookupError, SyntaxError) as error:
        raise ValueError(
            "Cannot decode this Python file; use valid UTF-8 or an encoding declaration."
        ) from error
    return filename, validate_source(code)
