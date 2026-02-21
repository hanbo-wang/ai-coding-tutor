"""Shared notebook JSON parsing utility for routers."""

import json

from fastapi import HTTPException, status


def parse_notebook_json_or_500(raw_json: str) -> dict:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored notebook JSON is invalid.",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored notebook JSON is invalid.",
        )
    return parsed
