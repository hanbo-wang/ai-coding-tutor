import pytest

from app.config import settings
from app.services.notebook_service import (
    NotebookValidationError,
    _derive_display_filename,
    _normalise_storage_segment,
    _normalise_title,
    ensure_user_notebook_storage_dir,
    ensure_zone_notebook_storage_dir,
)


def test_normalise_title_compacts_whitespace() -> None:
    assert _normalise_title("  Coursework   C  ") == "Coursework C"


def test_normalise_title_rejects_empty_value() -> None:
    with pytest.raises(NotebookValidationError):
        _normalise_title("   ")


def test_derive_display_filename_keeps_ipynb_extension() -> None:
    filename = _derive_display_filename("Coursework C", "old-name.ipynb")
    assert filename == "Coursework C.ipynb"


def test_derive_display_filename_uses_ipynb_when_extension_is_not_ipynb() -> None:
    filename = _derive_display_filename("Coursework C", "old-name.txt")
    assert filename == "Coursework C.ipynb"


def test_derive_display_filename_replaces_path_separators() -> None:
    filename = _derive_display_filename("Course/work\\C", "old-name.ipynb")
    assert filename == "Course-work-C.ipynb"


def test_normalise_storage_segment_replaces_unsafe_chars() -> None:
    folder_name = _normalise_storage_segment("../User Name+Math@Uni.ac.uk", fallback="fallback")
    assert folder_name == "user-name+math@uni.ac.uk"


def test_ensure_user_notebook_storage_dir_uses_email_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "notebook_storage_dir", str(tmp_path))

    user_dir = ensure_user_notebook_storage_dir("Alice.Example+Math@Uni.ac.uk")

    assert user_dir == tmp_path / "alice.example+math@uni.ac.uk"
    assert user_dir.exists()
    assert user_dir.is_dir()


def test_ensure_zone_notebook_storage_dir_uses_dedicated_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(settings, "notebook_storage_dir", str(tmp_path))

    zone_dir = ensure_zone_notebook_storage_dir()

    assert zone_dir == tmp_path / "learning_zone_notebooks"
    assert zone_dir.exists()
    assert zone_dir.is_dir()
