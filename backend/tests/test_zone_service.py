import pytest

from app.services.zone_service import (
    ZoneValidationError,
    _common_leading_folder,
    _derive_title_from_filename,
    _normalise_relative_path,
    _strip_leading_folder,
)


def test_normalise_relative_path_compacts_and_normalises() -> None:
    relative_path = _normalise_relative_path("  data\\week1//scores.csv ")
    assert relative_path == "data/week1/scores.csv"


def test_normalise_relative_path_rejects_parent_segments() -> None:
    with pytest.raises(ZoneValidationError):
        _normalise_relative_path("../secrets.txt")


def test_derive_title_from_filename_uses_stem() -> None:
    assert _derive_title_from_filename("week_03_intro.ipynb") == "week 03 intro"


def test_common_leading_folder_detects_shared_root() -> None:
    root = _common_leading_folder(["c6/a.py", "c6/b.py", "c6/data/x.csv"])
    assert root == "c6"


def test_strip_leading_folder_removes_prefix() -> None:
    assert _strip_leading_folder("c6/a.py", "c6") == "a.py"
