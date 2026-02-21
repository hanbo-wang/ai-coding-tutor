"""Upload service validation tests.

Run with:
    python -m unittest tests.test_upload_service
"""

import io
import unittest

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.services.upload_service import (
    UploadValidationError,
    classify_upload,
    get_upload_limits,
    validate_upload_count,
)


def make_upload(filename: str, content_type: str | None) -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type else None
    return UploadFile(
        io.BytesIO(b"test"),
        filename=filename,
        headers=headers,
    )


class UploadServiceTests(unittest.TestCase):
    def test_classify_upload_uses_mime_when_extension_missing(self) -> None:
        limits = get_upload_limits()
        file_type, max_bytes, extension = classify_upload(
            "clipboard-image",
            "image/png",
            limits,
        )

        self.assertEqual(file_type, "image")
        self.assertEqual(max_bytes, limits.max_image_bytes)
        self.assertEqual(extension, ".png")

    def test_validate_upload_count_accepts_mime_only_images_within_limit(self) -> None:
        limits = get_upload_limits()
        files = [make_upload("", "image/png") for _ in range(limits.max_images)]
        validate_upload_count(files, limits)

    def test_validate_upload_count_rejects_mime_only_images_over_limit(self) -> None:
        limits = get_upload_limits()
        files = [make_upload("", "image/png") for _ in range(limits.max_images + 1)]

        with self.assertRaises(UploadValidationError):
            validate_upload_count(files, limits)

    def test_validate_upload_count_rejects_unsupported_type(self) -> None:
        limits = get_upload_limits()
        files = [make_upload("", "image/bmp")]

        with self.assertRaises(UploadValidationError):
            validate_upload_count(files, limits)


if __name__ == "__main__":
    unittest.main()
