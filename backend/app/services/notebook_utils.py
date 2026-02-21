"""Shared notebook utilities for validation and file handling."""

import json
import os
from pathlib import Path


def normalise_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    return ext.lower()


def validate_notebook_payload(payload: dict, error_type: type[ValueError]) -> None:
    cells = payload.get("cells")
    if not isinstance(cells, list):
        raise error_type("Invalid notebook format: missing 'cells' array.")


def parse_ipynb_bytes(content: bytes, error_type: type[ValueError]) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise error_type("Notebook file must be UTF-8 JSON.") from exc

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise error_type("Invalid .ipynb file.") from exc

    if not isinstance(payload, dict):
        raise error_type("Notebook JSON must be an object.")
    validate_notebook_payload(payload, error_type)
    return text


def serialise_notebook_payload(
    payload: dict,
    max_size_bytes: int,
    max_size_mb: int,
    error_type: type[ValueError],
) -> str:
    validate_notebook_payload(payload, error_type)
    try:
        serialised = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise error_type("Invalid notebook JSON payload.") from exc

    if len(serialised.encode("utf-8")) > max_size_bytes:
        raise error_type(f"Notebook exceeds {max_size_mb} MB size limit.")
    return serialised


def safe_delete_file(path: str) -> None:
    try:
        file_path = Path(path)
        if file_path.exists():
            file_path.unlink()
    except OSError:
        # Best effort cleanup only.
        pass
