from __future__ import annotations

from pathlib import Path

from PIL import ImageGrab


class DesktopScreenshotClient:
    def save_screenshot(self, path: str) -> str:
        screenshot_path = Path(path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab()
        image.save(screenshot_path)
        return str(screenshot_path)
