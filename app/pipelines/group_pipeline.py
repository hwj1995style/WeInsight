from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class GroupPipelineState:
    pending_tasks: int
    failed_tasks: int

    def mark_failed(self) -> "GroupPipelineState":
        return replace(self, failed_tasks=self.failed_tasks + 1)
