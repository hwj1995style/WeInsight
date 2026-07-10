from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable


@dataclass(frozen=True)
class ProcessInfo:
    process_name: str
    process_id: int
    path: str | None
    version: str | None


class WechatHealthStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    VERSION_MISMATCH = "version_mismatch"


@dataclass(frozen=True)
class WechatHealth:
    status: WechatHealthStatus
    message: str
    process: ProcessInfo | None = None
    version: str | None = None


class WechatDesktopProbe:
    def __init__(
        self,
        *,
        expected_version: str,
        process_provider: Callable[[], list[ProcessInfo]] | None = None,
    ) -> None:
        self.expected_version = expected_version
        self.process_provider = process_provider or find_wechat_processes

    def check(self) -> WechatHealth:
        processes = self.process_provider()
        if not processes:
            return WechatHealth(
                status=WechatHealthStatus.NOT_FOUND,
                message="WeChat process was not found.",
            )

        process = _choose_main_process(processes)
        if process.version != self.expected_version:
            return WechatHealth(
                status=WechatHealthStatus.VERSION_MISMATCH,
                message=f"WeChat version mismatch: expected {self.expected_version}, got {process.version}.",
                process=process,
                version=process.version,
            )

        return WechatHealth(
            status=WechatHealthStatus.OK,
            message="WeChat desktop process is available.",
            process=process,
            version=process.version,
        )


def _choose_main_process(processes: list[ProcessInfo]) -> ProcessInfo:
    priority = {"Weixin": 0, "WeChat": 1, "WeChatAppEx": 2}
    return sorted(processes, key=lambda item: priority.get(item.process_name, 99))[0]


def find_wechat_processes() -> list[ProcessInfo]:
    script = r"""
$items = Get-Process | Where-Object { $_.ProcessName -in @('WeChat','Weixin','WeChatAppEx') } | ForEach-Object {
  $path = $_.Path
  $version = $null
  if ($path) {
    try { $version = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($path).FileVersion } catch { $version = $null }
  }
  [PSCustomObject]@{
    process_name = $_.ProcessName
    process_id = $_.Id
    path = $path
    version = $version
  }
}
$items | ConvertTo-Json -Compress
"""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []

    data = json.loads(completed.stdout)
    if isinstance(data, dict):
        rows = [data]
    else:
        rows = data

    return [
        ProcessInfo(
            process_name=str(row.get("process_name")),
            process_id=int(row.get("process_id")),
            path=row.get("path"),
            version=row.get("version"),
        )
        for row in rows
    ]
