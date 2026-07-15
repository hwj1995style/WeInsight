import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.windows_ocr_service import WindowsOcrService


def test_windows_ocr_service_returns_lines_and_removes_temp_file(monkeypatch) -> None:
    seen_path: Path | None = None

    def fake_run(command, **kwargs):
        nonlocal seen_path
        seen_path = Path(command[-1])
        assert seen_path.read_bytes() == b"image"
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(["第一行", "48 -1 262 262 0"], ensure_ascii=False),
            stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    service = WindowsOcrService(script_path=Path("scripts/windows_ocr.ps1"))

    assert service.recognize(b"image") == ["第一行", "48 -1 262 262 0"]
    assert seen_path is not None
    assert not seen_path.exists()


def test_windows_ocr_service_rejects_empty_or_oversized_images() -> None:
    service = WindowsOcrService(
        script_path=Path("scripts/windows_ocr.ps1"), max_image_bytes=4
    )

    with pytest.raises(ValueError, match="image_bytes"):
        service.recognize(b"")
    with pytest.raises(ValueError, match="image_bytes"):
        service.recognize(b"12345")


def test_windows_ocr_service_raises_sanitized_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="sensitive path"
        ),
    )
    service = WindowsOcrService(script_path=Path("scripts/windows_ocr.ps1"))

    with pytest.raises(RuntimeError, match="windows_ocr_failed"):
        service.recognize(b"image")
