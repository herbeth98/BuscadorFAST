"""Linha de comando.

    python -m buscador abrir               abre a tela no navegador (padrão)
    python -m buscador indexar E:\\ G:\\Fotos  indexa pastas ou discos inteiros e roda a IA
    python -m buscador ia [--refazer]      gera palavras-chave nos arquivos pendentes
    python -m buscador rostos              procura rostos nos arquivos pendentes e agrupa
    python -m buscador texto               lê o texto escrito dentro das fotos (OCR)
    python -m buscador transcrever         transcreve a fala dos vídeos (Whisper)
    python -m buscador pendentes           faz tudo o que falta: palavras-chave, rostos, texto e fala
    python -m buscador atualizar           percorre todos os discos marcados e depois faz o que falta
    python -m buscador duplicados          procura arquivos idênticos (não apaga nada)
    python -m buscador backup              copia o catálogo para o disco de backup
    python -m buscador restaurar-backup X  volta o catálogo de um backup (com o programa fechado)
    python -m buscador discos              lista os discos do catálogo
    python -m buscador modelos             baixa de uma vez todos os modelos de IA (o instalador usa)
"""
import argparse
import sys
import threading
import time
import webbrowser


def _print_progress(p: dict) -> None:
    done, total = p.get("done"), p.get("total")
    extra = f" {done}/{total}" if total else f" {p.get('found', '')} encontrados"
    rate = f"  ({p['per_hour']}/hora)" if p.get("per_hour") else ""
    sys.stdout.write(f"\r{p.get('phase', '')}:{extra}{rate}".ljust(90))
    sys.stdout.flush()


def main() -> None:
    ap = argparse.ArgumentParser(prog="buscador")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("indexar"); s.add_argument("pastas", nargs="+"); s.add_argument("--sem-ia", action="store_true")
    s = sub.add_parser("ia"); s.add_argument("--refazer", action="store_true")
    sub.add_parser("discos")
    sub.add_parser("rostos")
    sub.add_parser("texto")
    sub.add_parser("transcrever")
    sub.add_parser("pendentes")
    sub.add_parser("atualizar")
    sub.add_parser("duplicados")
    sub.add_parser("backup")
    sub.add_parser("modelos")
    s = sub.add_parser("restaurar-backup"); s.add_argument("arquivo")
    s = sub.add_parser("abrir"); s.add_argument("--porta", type=int, default=8765); s.add_argument("--sem-navegador", action="store_true")
    args = ap.parse_args()

    if args.cmd == "modelos":
        from . import modelos
        modelos.baixar_tudo()
    elif args.cmd == "backup":
        from . import backup
        r = backup.run()
        print(f"Backup salvo em {r['file']} ({r['size'] / 1e6:.0f} MB; {r['copied']} miniaturas/rostos copiados)")
    elif args.cmd == "restaurar-backup":
        from . import backup
        safety = backup.restore(args.arquivo)
        print(f"Catálogo restaurado. O catálogo anterior ficou guardado em {safety}")
    elif args.cmd == "duplicados":
        from . import dupes
        r = dupes.find(progress=_print_progress)
        print(f"\n{r.get('groups', 0)} grupos de duplicados; {r.get('waste', 0) / 1e9:.1f} GB podem ser liberados")
    elif args.cmd in ("indexar", "rostos", "ia", "texto", "transcrever", "pendentes", "atualizar"):
        from . import control
        stop = control.StopSignal()  # o botão Parar da tela também interrompe a linha de comando
        control.keep_awake(True)     # não deixa o PC suspender enquanto o comando roda
        status = control.Status({"indexar": "scan", "atualizar": "scan", "texto": "ocr",
                                 "transcrever": "fala"}.get(args.cmd, args.cmd))

        def prog(p: dict) -> None:
            _print_progress(p)
            status.update(p)

        try:
            if args.cmd == "indexar":
                from . import scanner
                from .jobs import stages
                for pasta in args.pastas:
                    if stop.is_set():
                        break
                    print(f"\n== {pasta}")
                    status.update(kind="scan", path=pasta)
                    r = scanner.scan(pasta, progress=prog, stop=stop)
                    print(f"\n{r['found']} arquivos: {r['new']} novos, {r['changed']} alterados, "
                          f"{r['unchanged']} sem mudança, {r['missing']} sumiram, {r['errors']} com erro "
                          f"({r['seconds']}s)")
                for name, run in ([] if args.sem_ia else stages()):
                    if stop.is_set():
                        break
                    status.update(kind=name, path=None)
                    r = run(progress=prog, stop=stop)
                    print(f"\n{name}: {r.get('done', r.get('total', 0))} arquivos")
            elif args.cmd in ("pendentes", "atualizar"):
                from . import scanner
                if args.cmd == "atualizar":
                    from .atualizar import roots
                    for r in [r for r in roots() if r["included"]]:
                        if stop.is_set():
                            break
                        print(f"\n== {r['root']} ({r['label']})")
                        status.update(kind="scan", path=f"{r['root']} ({r['label']})")
                        s = scanner.scan(r["root"], progress=prog, stop=stop)
                        print(f"\n{s['found']} arquivos: {s['new']} novos, {s['changed']} alterados, "
                              f"{s['missing']} sumiram, {s['errors']} com erro ({s['seconds']}s)")
                from .jobs import stages
                for name, run in stages():
                    if stop.is_set():
                        break
                    status.update(kind=name)
                    r = run(progress=prog, stop=stop)
                    print(f"\n{name}: {r.get('done', r.get('total', 0))} arquivos")
            elif args.cmd == "transcrever":
                from . import speech
                r = speech.process_pending(progress=prog, stop=stop)
                print(f"\nFala: {r.get('with_speech', 0)} de {r.get('total', 0)} vídeos têm fala")
            elif args.cmd == "texto":
                from . import ocr
                r = ocr.process_pending(progress=prog, stop=stop)
                print(f"\nTexto: {r.get('with_text', 0)} de {r.get('total', 0)} arquivos têm texto escrito")
            elif args.cmd == "rostos":
                from . import faces
                r = faces.process_pending(progress=prog, stop=stop)
                print(f"\nRostos: {r.get('faces', 0)} em {r.get('total', 0)} arquivos")
            else:
                from . import ai
                r = ai.process_pending(progress=prog, redo=args.refazer, stop=stop)
                print(f"\nIA: {r.get('done', 0)} arquivos")
            if stop.is_set():
                print("\nParado pelo botão Parar. Rode de novo para continuar de onde parou.")
        finally:
            status.finish()
    elif args.cmd == "discos":
        from .volumes import list_volumes
        for v in list_volumes():
            estado = f"conectado em {v['letter']}:" if v["online"] else "DESCONECTADO"
            print(f"{v['label']:<20} {v['serial']}  {estado:<16} {v['files'] or 0:>8} arquivos  "
                  f"({v['pending_ai'] or 0} aguardando IA)")
    else:
        import uvicorn
        port = getattr(args, "porta", 8765)
        url = f"http://127.0.0.1:{port}"
        if sys.stdout is None:  # aberto pelo BuscadorFAST.exe (pythonw, sem console): grava num log
            from .config import DATA_DIR
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            log = open(DATA_DIR / "servidor.log", "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = log
        if not getattr(args, "sem_navegador", False):
            threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
        print(f"BuscadorFAST em {url}  (feche esta janela para encerrar)")
        uvicorn.run("buscador.server:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
