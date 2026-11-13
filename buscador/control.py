"""Progresso e botão "Parar" que funcionam entre processos.

A indexação pode rodar pela tela (servidor) ou pela linha de comando. As duas gravam o progresso em
data/tarefa.json e olham o arquivo data/parar.flag: o botão Parar da tela cria esse arquivo e
qualquer tarefa em andamento para no próximo arquivo.
"""
import json
import os
import time

from .config import DATA_DIR

STOP_FLAG = DATA_DIR / "parar.flag"
STATUS_FILE = DATA_DIR / "tarefa.json"


def keep_awake(on: bool) -> None:
    """Pede ao Windows para não suspender o PC enquanto uma tarefa roda (vale para esta thread).
    Não muda nenhuma configuração de energia: ao desligar, o Windows volta a suspender normalmente."""
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def request_stop() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STOP_FLAG.write_text(str(time.time()))


class StopSignal:
    """Mesma interface do threading.Event (is_set), mas lê o pedido de parada do disco."""

    def __init__(self) -> None:
        self.started = time.time()
        self._checked = 0.0
        self._stopped = False
        STOP_FLAG.unlink(missing_ok=True)

    def is_set(self) -> bool:
        if self._stopped:
            return True
        now = time.time()
        if now - self._checked > 0.5:  # no máximo duas leituras por segundo
            self._checked = now
            try:
                self._stopped = STOP_FLAG.stat().st_mtime >= self.started
            except FileNotFoundError:
                pass
        return self._stopped


class Status:
    """Grava o progresso da tarefa da linha de comando para a tela mostrar."""

    def __init__(self, kind: str, path: str | None = None) -> None:
        self.data = {"kind": kind, "path": path, "pid": os.getpid(), "progress": {}, "external": True,
                     "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._last = 0.0

    def update(self, progress: dict | None = None, **kw) -> None:
        if progress is not None:
            self.data["progress"] = progress
        self.data.update(kw)
        now = time.time()
        if now - self._last > 1:
            self._last = now
            self.data["updated"] = now
            try:
                STATUS_FILE.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass

    def finish(self) -> None:
        STATUS_FILE.unlink(missing_ok=True)


def external_status() -> dict | None:
    """Tarefa da linha de comando em andamento (se o arquivo foi atualizado há pouco)."""
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return None
    if time.time() - data.get("updated", 0) > 60:
        return None
    data["stopping"] = STOP_FLAG.exists()
    return data
