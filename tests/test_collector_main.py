from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.workers import collector_main


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


class Scheduler:
    def __init__(self, **kwargs):
        self.jobs = []

    def add_job(self, callback, trigger, **kwargs):
        self.jobs.append((callback, trigger, kwargs))

    def start(self):
        pass

    def shutdown(self, wait):
        pass


def test_registers_global_cycle_with_single_coalesced_instance():
    scheduler = Scheduler()
    cycle = SimpleNamespace(run=lambda now: None)

    collector_main._register_article_global_cycle(scheduler, cycle, 13, lambda: NOW)

    callback, trigger, kwargs = scheduler.jobs[0]
    assert trigger == "interval"
    assert kwargs == {"minutes": 13, "max_instances": 1, "coalesce": True}
    assert callback() is None
