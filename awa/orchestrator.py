"""A small DAG task orchestrator.

- Tasks declare dependencies; independent tasks run in parallel threads.
- Each task gets retries with linear backoff.
- A failed task skips everything downstream of it (not the whole run).
- Every task is timed, so a run produces real, measured durations.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("awa")


@dataclass
class Task:
    name: str
    fn: Callable[["RunContext"], Any]
    deps: tuple[str, ...] = ()
    retries: int = 0
    retry_delay: float = 1.0
    description: str = ""


@dataclass
class TaskRun:
    name: str
    status: str = "pending"  # pending | running | success | failed | skipped
    attempts: int = 0
    start_offset: float | None = None  # seconds since run start
    seconds: float = 0.0
    error: str | None = None


@dataclass
class RunContext:
    run_id: str
    out_dir: Path
    config: dict[str, Any]
    llm: Any = None
    results: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def result(self, task_name: str) -> Any:
        return self.results[task_name]

    def count(self, key: str, n: int | float = 1) -> None:
        with self._lock:
            self.metrics[key] = self.metrics.get(key, 0) + n

    def set_metric(self, key: str, value: Any) -> None:
        with self._lock:
            self.metrics[key] = value


class CycleError(ValueError):
    pass


class Workflow:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tasks: dict[str, Task] = {}

    def add(self, task: Task) -> Task:
        if task.name in self.tasks:
            raise ValueError(f"duplicate task '{task.name}'")
        self.tasks[task.name] = task
        return task

    def task(self, name: str, deps: tuple[str, ...] = (), retries: int = 0, description: str = ""):
        """Decorator form of `add`."""

        def deco(fn: Callable[[RunContext], Any]) -> Callable[[RunContext], Any]:
            self.add(Task(name, fn, tuple(deps), retries, description=description or (fn.__doc__ or "").strip()))
            return fn

        return deco

    # ----------------------------------------------------------------- checks
    def topological_order(self) -> list[str]:
        for t in self.tasks.values():
            for d in t.deps:
                if d not in self.tasks:
                    raise ValueError(f"task '{t.name}' depends on unknown task '{d}'")
        indeg = {n: len(t.deps) for n, t in self.tasks.items()}
        order: list[str] = []
        ready = [n for n, k in indeg.items() if k == 0]
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m, t in self.tasks.items():
                if n in t.deps:
                    indeg[m] -= 1
                    if indeg[m] == 0:
                        ready.append(m)
        if len(order) != len(self.tasks):
            raise CycleError(f"dependency cycle among: {sorted(set(self.tasks) - set(order))}")
        return order

    # -------------------------------------------------------------------- run
    def run(self, ctx: RunContext, max_workers: int = 4) -> dict[str, Any]:
        self.topological_order()
        runs = {n: TaskRun(n) for n in self.tasks}
        pending = set(self.tasks)
        running: dict[Future, str] = {}
        t_start = time.perf_counter()
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        log.info("workflow %s started (run %s)", self.name, ctx.run_id)

        def execute(task: Task, tr: TaskRun) -> Any:
            tr.status = "running"
            tr.start_offset = round(time.perf_counter() - t_start, 3)
            t0 = time.perf_counter()
            try:
                for attempt in range(1, task.retries + 2):
                    tr.attempts = attempt
                    try:
                        return task.fn(ctx)
                    except Exception as e:  # noqa: BLE001 - we record and maybe retry
                        if attempt > task.retries:
                            raise
                        log.warning("task %s attempt %d failed: %s (retrying)", task.name, attempt, e)
                        time.sleep(task.retry_delay * attempt)
            finally:
                tr.seconds = round(time.perf_counter() - t0, 3)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while pending or running:
                changed = True
                while changed:  # propagate skips / start everything that is ready
                    changed = False
                    for name in sorted(pending):
                        task = self.tasks[name]
                        dep_status = [runs[d].status for d in task.deps]
                        if any(s in ("failed", "skipped") for s in dep_status):
                            runs[name].status = "skipped"
                            runs[name].error = "upstream task failed"
                            pending.discard(name)
                            log.warning("task %s skipped (upstream failed)", name)
                            changed = True
                        elif all(s == "success" for s in dep_status):
                            pending.discard(name)
                            log.info("task %s started", name)
                            running[pool.submit(execute, task, runs[name])] = name
                            changed = True
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in done:
                    name = running.pop(fut)
                    tr = runs[name]
                    try:
                        ctx.results[name] = fut.result()
                        tr.status = "success"
                        log.info("task %s done in %.2fs", name, tr.seconds)
                    except Exception as e:  # noqa: BLE001
                        tr.status = "failed"
                        tr.error = f"{type(e).__name__}: {e}"
                        log.error("task %s failed: %s", name, tr.error)

        total = round(time.perf_counter() - t_start, 3)
        ok = all(r.status == "success" for r in runs.values())
        log.info("workflow %s %s in %.2fs", self.name, "succeeded" if ok else "finished with failures", total)
        return {
            "workflow": self.name,
            "run_id": ctx.run_id,
            "started_at": started_at,
            "status": "success" if ok else "failed",
            "total_seconds": total,
            "tasks": [asdict(runs[n]) | {"deps": list(self.tasks[n].deps), "description": self.tasks[n].description}
                      for n in self.topological_order()],
        }
