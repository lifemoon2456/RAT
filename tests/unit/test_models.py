import pytest
from pydantic import ValidationError

from rat.domain.models import SourceUnit


def test_source_is_frozen_and_hash_checked(source):
    for field in ("source_text", "old", "renpy_identifier"):
        with pytest.raises(ValidationError):
            setattr(source, field, "changed")
    assert len(source.source_sha256) == 64
    data = source.model_dump()
    data["source_text"] = "changed"
    with pytest.raises(ValidationError, match="hash"):
        SourceUnit.model_validate(data)


@pytest.mark.parametrize("path", ["../script.rpy", "C:/game/script.rpy", "/game/a.rpy", "a\\b.rpy"])
def test_source_path_is_relative(source, path):
    with pytest.raises(ValidationError):
        SourceUnit.model_validate({**source.model_dump(), "source_relpath": path})


def test_no_invented_identifier_or_location(source):
    data = source.model_dump(exclude={"source_sha256"})
    data.update(renpy_identifier=None, source_line=None)
    with pytest.raises(ValidationError, match="precise source line"):
        SourceUnit.model_validate(data)
