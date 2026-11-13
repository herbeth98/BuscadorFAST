"""Atualização automática toda noite, pelo Agendador de Tarefas do Windows (tarefas do seu usuário).

Duas tarefas na pasta "BuscadorFAST" do Agendador:
  Atualizar → na hora de início, abre o programa se preciso e roda "Atualizar todos os discos"
  Parar     → na hora de fim, para o que estiver rodando (continua de onde parou na noite seguinte)
"""
import re
import subprocess

from .config import ROOT

TASK_START = r"BuscadorFAST\Atualizar"
TASK_STOP = r"BuscadorFAST\Parar"
SCRIPT = ROOT / "launcher" / "noturno.ps1"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, creationflags=NO_WINDOW)


def _action(acao: str) -> str:
    return (f'powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
            f'-File "{SCRIPT}" {acao}')


def status() -> dict:
    def query(name):
        out = _run(["/Query", "/TN", name, "/FO", "LIST", "/V"])
        if out.returncode != 0:
            return None
        text = out.stdout.decode("cp850", "replace")
        m = re.search(r"(?:Hora de início|Start Time):\s*(\d{1,2}:\d{2})", text)
        return m.group(1) if m else "?"
    start, stop = query(TASK_START), query(TASK_STOP)
    return {"enabled": start is not None, "start": start or "01:00", "stop": stop or "07:00"}


def enable(start: str, stop: str) -> dict:
    for t in (start, stop):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("use o formato HH:MM")
    for name, acao, hora in ((TASK_START, "iniciar", start), (TASK_STOP, "parar", stop)):
        out = _run(["/Create", "/F", "/SC", "DAILY", "/TN", name, "/TR", _action(acao), "/ST", hora])
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode("cp850", "replace").strip() or "o Windows recusou o agendamento")
    return status()


def disable() -> dict:
    for name in (TASK_START, TASK_STOP):
        _run(["/Delete", "/F", "/TN", name])
    return status()
