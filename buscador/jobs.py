"""Fila de tarefas em segundo plano (indexar pastas e rodar a IA), uma de cada vez."""
import queue
import threading
import time
import traceback
from datetime import datetime

from . import control

_queue: "queue.Queue[dict]" = queue.Queue()
_state = {"current": None, "history": [], "queued": []}
_started = False
_lock = threading.Lock()


def _light(job: dict | None) -> dict | None:
    """Sem a lista de arquivos (pode ter milhares) — a tela consulta isto a cada segundo."""
    big = [k for k in ("ids", "paths") if job and k in job]
    if not big:
        return job
    return {k: v for k, v in job.items() if k not in big} | {"count": len(job[big[0]])}


def status() -> dict:
    with _lock:
        current = _state["current"]
        if current is None:
            current = control.external_status()  # indexação rodando pela linha de comando
        elif control.STOP_FLAG.exists():
            current = {**current, "stopping": True}
        return {"current": _light(current), "queued": [_light(j) for j in _state["queued"]],
                "history": [_light(j) for j in _state["history"][-10:]]}


def _set(**kw):
    with _lock:
        if _state["current"] is not None:
            _state["current"].update(kw)


def submit(kind: str, path: str | None = None, redo: bool = False, **extra) -> None:
    job = {"kind": kind, "path": path, "redo": redo, **extra}
    with _lock:
        _state["queued"].append(job)
    _queue.put(job)
    _ensure_worker()


def submit_files(paths: list[str]) -> None:
    """Arquivos novos vistos pela vigilância: junta numa tarefa só se já houver uma esperando na fila."""
    with _lock:
        for job in _state["queued"]:
            if job["kind"] == "arquivos":
                job["paths"] = list(dict.fromkeys(job["paths"] + paths))
                return
    submit("arquivos", paths=list(paths))


def cancel() -> None:
    """Para a tarefa atual (desta tela ou da linha de comando) e esvazia a fila."""
    with _lock:
        _state["queued"].clear()
        while True:
            try:
                _queue.get_nowait()
            except queue.Empty:
                break
    control.request_stop()


def _ensure_worker():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_worker, daemon=True).start()


def stages():
    """Etapas depois de ler o disco, na ordem. Cada uma só trabalha no que ainda falta para ela."""
    from . import ai, descricao, faces, lightroom, ocr, qualidade, som, speech
    return [
        ("lightroom", lightroom.process_pending),  # palavras-chave e estrelas que você já pôs no Lightroom
        ("ia", ai.process_pending),                # palavras-chave da lista + busca por frase livre
        ("qualidade", qualidade.process_pending),  # fotos borradas, escuras, estouradas, rajadas → "Para revisar"
        ("descricao", descricao.process_pending),  # descrição em português e palavras livres
        ("rostos", faces.process_pending),
        ("ocr", ocr.process_pending),
        ("fala", speech.process_pending),
        ("som", som.process_pending),              # aplausos, fogos, música, torcida… com o momento
    ]


# Três frentes ao mesmo tempo, cada uma usando uma parte diferente do PC
LANES = {
    "imagem": ["lightroom", "ia", "qualidade", "descricao", "rostos"],  # placa de vídeo, a partir das miniaturas
    "audio": ["fala", "som"],                                          # disco + placa de vídeo
    "texto": ["ocr"],                                                  # disco (lê os originais)
}
LANE_LABEL = {"imagem": "Imagens", "audio": "Áudio", "texto": "Texto nas fotos"}


def _lane_progress(lane: str, stage: str, p: dict) -> None:
    with _lock:
        cur = _state["current"]
        if cur is not None:
            cur.setdefault("lanes", {})[lane] = {"stage": stage, **p}


def _run_stages(result: dict, prog, stop, only=None, scanning: threading.Event | None = None) -> None:
    """Roda as etapas em três frentes paralelas. Enquanto `scanning` estiver ligado (discos ainda sendo lidos),
    cada frente volta a procurar trabalho de tempos em tempos; uma etapa que falhar é tentada de novo depois,
    sem derrubar as outras."""
    if only is not None and not only:
        return
    fns = dict(stages())

    def lane(name: str, kinds: list[str]) -> None:
        last: dict[str, int] = {}
        fails: dict[str, int] = {}
        while not stop.is_set():
            worked = 0
            for k in kinds:
                if stop.is_set() or fails.get(k, 0) >= 3:  # três erros seguidos: desiste desta etapa por agora
                    continue
                extra = {"keep_loaded": True} if k == "descricao" else {}  # não recarrega o modelo a cada volta
                try:
                    r = fns[k](progress=lambda p, k=k: _lane_progress(name, k, p), stop=stop, only_ids=only, **extra)
                    result[k] = r
                    fails[k] = 0
                    total = (r or {}).get("total", 0) or 0
                    # se sobrou o mesmo tanto da volta anterior, são arquivos que não andam: não conta como trabalho
                    if total and total != last.get(k):
                        worked += total
                    last[k] = total
                except Exception as exc:  # ex.: banco ocupado, falta de memória na placa: tenta na próxima volta
                    traceback.print_exc()
                    result[k] = {"error": f"{type(exc).__name__}: {exc}"}
                    fails[k] = fails.get(k, 0) + 1
                    worked += 1
                    time.sleep(10)
            still_scanning = scanning is not None and scanning.is_set()
            if not worked and not still_scanning:
                break
            if not worked or only is not None:
                if only is not None and not still_scanning:
                    break
                time.sleep(20)  # os discos ainda estão sendo lidos: espera chegar mais coisa
        _lane_progress(name, "pronto", {"phase": "concluído"})

    threads = [threading.Thread(target=lane, args=(n, ks), daemon=True, name=f"frente-{n}") for n, ks in LANES.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    from . import descricao
    descricao.unload()  # libera a placa de vídeo para o resto do PC


def _worker():
    from . import ai, dupes, faces, ocr, scanner, speech

    while True:
        if _queue.empty():
            control.keep_awake(False)  # nada na fila: o PC pode voltar a suspender
        job = _queue.get()
        control.keep_awake(True)       # trabalhando: não deixa o PC dormir no meio
        stop = control.StopSignal()
        with _lock:
            if job in _state["queued"]:
                _state["queued"].remove(job)
            _state["current"] = {**job, "started": datetime.now().isoformat(timespec="seconds"), "progress": {}}
        prog = lambda p: _set(progress=p)  # noqa: E731
        try:
            if job["kind"] == "scan":
                result = scanner.scan(job["path"], progress=prog, stop=stop)
                new_ids = result.pop("new_ids")
                # "only_new": arquivos que chegaram do celular — não puxa a fila inteira de pendentes junto
                only = set(new_ids) if job.get("only_new") else None
                _run_stages(result, prog, stop, only)
            elif job["kind"] == "arquivos":
                # arquivos novos vistos pela vigilância: só eles passam pelas etapas
                result = scanner.scan_paths(job["paths"], progress=prog, stop=stop)
                _run_stages(result, prog, stop, set(result.pop("new_ids")))
            elif job["kind"] == "atualizar":
                # todos os discos conectados, um depois do outro; depois tudo o que ficou pendente
                from .atualizar import roots
                result = {"discos": []}
                scanning = threading.Event()
                scanning.set()

                def scan_all():
                    try:
                        for r in [r for r in roots() if r["included"]]:
                            if stop.is_set():
                                break
                            _set(kind="scan", path=f"{r['root']} ({r['label']})")
                            s = scanner.scan(r["root"], progress=prog, stop=stop)
                            s.pop("new_ids", None)
                            result["discos"].append({"root": r["root"], "new": s["new"], "changed": s["changed"],
                                                     "missing": s["missing"], "errors": s["errors"]})
                    finally:
                        scanning.clear()
                        _set(kind="etapas", path=None, progress={"phase": "discos lidos; terminando as etapas"})

                # lê os discos e, ao mesmo tempo, já processa o que tem miniatura
                reader = threading.Thread(target=scan_all, daemon=True, name="leitura-discos")
                reader.start()
                _run_stages(result, prog, stop, scanning=scanning)
                reader.join()
            elif job["kind"] == "pendentes":
                # tudo o que ficou para trás, na mesma ordem da indexação
                result = {}
                _run_stages(result, prog, stop)
            elif job["kind"] == "xmp":
                from . import xmp
                result = xmp.write(job["ids"], job["mode"], job["include_ai"], progress=prog, stop=stop)
            elif job["kind"] == "leitura":
                from . import leitura
                result = leitura.run(job.get("hours", 3), progress=prog, stop=stop)
            elif job["kind"] == "duplicados":
                result = dupes.find(progress=prog, stop=stop)
            elif job["kind"] == "fala":
                result = speech.process_pending(progress=prog, stop=stop)
            elif job["kind"] == "rostos":
                result = faces.process_pending(progress=prog, stop=stop)
            elif job["kind"] == "ocr":
                result = ocr.process_pending(progress=prog, stop=stop)
            else:
                result = ai.process_pending(progress=prog, redo=job["redo"], stop=stop)
            outcome = {"ok": True, "stopped": stop.is_set(), "result": result}
        except Exception as exc:
            traceback.print_exc()
            outcome = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        with _lock:
            done = {**_state["current"], **outcome, "finished": datetime.now().isoformat(timespec="seconds")}
            done.pop("progress", None)
            _state["history"].append(done)
            _state["current"] = None
