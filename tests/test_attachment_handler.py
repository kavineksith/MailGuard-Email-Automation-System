import pytest

from core.exceptions import (
    AttachmentNotFoundError,
    AttachmentTooLargeError,
    UnsupportedAttachmentTypeError,
)
from services.attachment_handler import AttachmentHandler, MAX_ATTACHMENT_SIZE


@pytest.mark.asyncio
async def test_validate_missing_file_raises(tmp_path):
    with pytest.raises(AttachmentNotFoundError):
        await AttachmentHandler.validate(str(tmp_path / "missing.pdf"))


@pytest.mark.asyncio
async def test_validate_unsupported_extension_raises(tmp_path):
    file_path = tmp_path / "payload.exe"
    file_path.write_bytes(b"data")
    with pytest.raises(UnsupportedAttachmentTypeError):
        await AttachmentHandler.validate(str(file_path))


@pytest.mark.asyncio
async def test_validate_oversized_file_raises(tmp_path):
    file_path = tmp_path / "big.txt"
    with open(file_path, "wb") as f:
        f.seek(MAX_ATTACHMENT_SIZE + 1)
        f.write(b"\0")
    with pytest.raises(AttachmentTooLargeError):
        await AttachmentHandler.validate(str(file_path))


@pytest.mark.asyncio
async def test_validate_valid_file_returns_path(tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello")
    result = await AttachmentHandler.validate(str(file_path))
    assert result.name == "report.txt"


@pytest.mark.asyncio
async def test_build_part_sets_headers(tmp_path):
    file_path = tmp_path / "report.txt"
    file_path.write_text("hello world")
    part = await AttachmentHandler.build_part(str(file_path))
    assert part["Content-Disposition"].endswith('filename="report.txt"')
    assert part["X-Content-Type-Options"] == "nosniff"


@pytest.mark.asyncio
async def test_validate_batch_reports_mixed_results(tmp_path):
    good = tmp_path / "good.txt"
    good.write_text("ok")
    paths = [str(good), str(tmp_path / "missing.txt")]
    results = [r async for r in AttachmentHandler.validate_batch(paths)]
    assert results[0][1] is True
    assert results[1][1] is False


@pytest.mark.asyncio
async def test_build_parts_concurrent(tmp_path):
    files = []
    for i in range(3):
        p = tmp_path / f"f{i}.txt"
        p.write_text("content")
        files.append(str(p))
    parts = await AttachmentHandler.build_parts(files)
    assert len(parts) == 3
