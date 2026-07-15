from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
import subprocess
import tempfile


class WindowsOcrService:
    def __init__(
        self,
        *,
        script_path: Path | None = None,
        timeout_seconds: int = 30,
        max_image_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self.script_path = script_path or (
            Path(__file__).resolve().parents[2] / "scripts" / "windows_ocr.ps1"
        )
        self.timeout_seconds = timeout_seconds
        self.max_image_bytes = max_image_bytes

    def recognize(self, image_bytes: bytes) -> list[str]:
        if not image_bytes or len(image_bytes) > self.max_image_bytes:
            raise ValueError("image_bytes must be non-empty and within size limit")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".img") as handle:
                handle.write(image_bytes)
                temp_path = Path(handle.name)
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(self.script_path),
                    "-InputPath",
                    str(temp_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8-sig",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                raise RuntimeError("windows_ocr_failed")
            payload = json.loads(completed.stdout.lstrip("\ufeff").strip() or "[]")
            if isinstance(payload, str):
                payload = [payload]
            if not isinstance(payload, list):
                raise RuntimeError("windows_ocr_invalid_output")
            return [str(line).strip() for line in payload[:200] if str(line).strip()]
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise RuntimeError("windows_ocr_failed") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def recognize_account(self, account_name: str, image_bytes: bytes) -> list[str]:
        if account_name != "河南金咕咕蛋品":
            return self.recognize(image_bytes)
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        except ImportError:
            return self.recognize(image_bytes)

        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        if image.width < 800 or image.height < 450:
            return self.recognize(image_bytes)
        lines: list[str] = []
        row_top = round(image.height * 0.361)
        row_height = max(1, round(image.height * 0.096))
        for row_index in range(5):
            top = row_top + row_index * row_height
            bottom = min(image.height, top + row_height)
            spec = image.crop(
                (round(image.width * 0.069), top, round(image.width * 0.292), bottom)
            )
            price = image.crop(
                (round(image.width * 0.278), top, round(image.width * 0.50), bottom)
            )
            parts = [
                *self._recognize_enlarged_crop(
                    spec, Image, ImageEnhance, ImageFilter, ImageOps
                ),
                *self._recognize_enlarged_crop(
                    price, Image, ImageEnhance, ImageFilter, ImageOps
                ),
            ]
            if parts:
                lines.append(" ".join(parts))
        return lines

    def _recognize_enlarged_crop(
        self, crop, Image, ImageEnhance, ImageFilter, ImageOps
    ) -> list[str]:
        crop = crop.resize(
            (crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS
        )
        crop = ImageOps.autocontrast(crop)
        crop = ImageEnhance.Contrast(crop).enhance(1.8)
        crop = crop.filter(ImageFilter.SHARPEN)
        output = BytesIO()
        crop.save(output, format="PNG")
        return self.recognize(output.getvalue())
