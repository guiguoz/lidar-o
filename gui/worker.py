"""Thread d'exécution du pipeline — découplé de l'interface."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable


@dataclass
class Progress:
    step: str
    step_idx: int
    total_steps: int
    message: str


@dataclass
class Done:
    success: bool
    error: str | None = None


class PipelineWorker:
    """Lance le pipeline dans un thread séparé. Pousse Progress + Done dans la queue."""

    def __init__(self, message_queue: queue.Queue) -> None:
        self._q = message_queue
        self._thread: threading.Thread | None = None
        self._cancel_event = threading.Event()

    def start(self, run_fn: Callable[[], None]) -> None:
        self._cancel_event.clear()
        self._thread = threading.Thread(target=self._run, args=(run_fn,), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self, run_fn: Callable[[], None]) -> None:
        try:
            run_fn()
            self._q.put(Done(success=True))
        except Exception as exc:
            self._q.put(Done(success=False, error=str(exc)))
