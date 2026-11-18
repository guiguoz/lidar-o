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
        result: Done | None = None
        try:
            run_fn()
            result = Done(success=True)
        except SystemExit as exc:
            # sys.exit() est utilisé par _cmd_run quand cmd_check échoue.
            # SystemExit n'hérite pas de Exception → doit être capturé séparément.
            code = exc.code
            if isinstance(code, int) and code == 0:
                result = Done(success=True)
            elif isinstance(code, str) and code:
                result = Done(success=False, error=code.strip())
            else:
                result = Done(success=False, error="Projet incomplet — corriger les points ci-dessus.")
        except Exception as exc:
            result = Done(success=False, error=str(exc))
        finally:
            # Garantit que l'interface est toujours réactivée, même en cas
            # d'exception imprévue (BaseException, KeyboardInterrupt, etc.).
            # Les modifications Tkinter sont faites sur le thread principal
            # via la queue dans _update_ui — ce put() est thread-safe.
            if result is None:
                result = Done(success=False, error="Erreur inattendue — voir la console.")
            self._q.put(result)
