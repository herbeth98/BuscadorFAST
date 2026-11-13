"""Conexão com o Adobe Premiere Pro pelo painel "MCP Bridge (CEP)" que já está instalado.

O painel lê arquivos command-<id>.json numa pasta temporária, roda o script (ExtendScript) dentro do
Premiere e devolve response-<id>.json. O BuscadorFAST usa o mesmo caminho para importar arquivos.
"""
import json
import os
import time
import uuid
from pathlib import Path

TICKS_PER_SECOND = 254016000000


def bridge_dir() -> Path:
    cfg = Path.home() / ".premiere-mcp-bridge" / "config.json"
    try:
        d = json.loads(cfg.read_text(encoding="utf-8")).get("tempDirectory")
        if d:
            return Path(d)
    except (FileNotFoundError, ValueError, OSError):
        pass
    return Path(os.environ.get("PREMIERE_TEMP_DIR") or Path(os.environ.get("TEMP", "C:\\Temp")) / "premiere-mcp-bridge")


def heartbeat_age() -> float | None:
    try:
        data = json.loads((bridge_dir() / "bridge-heartbeat.json").read_text(encoding="utf-8"))
        return time.time() - data["t"] / 1000
    except (FileNotFoundError, ValueError, KeyError, OSError):
        return None


def run(script: str, timeout: float = 120) -> str:
    """Roda um ExtendScript no Premiere e devolve o resultado (texto)."""
    age = heartbeat_age()
    if age is None or age > 15:
        raise ConnectionError("O Premiere não está aberto (ou o painel MCP Bridge não está rodando).")
    d = bridge_dir()
    cid = f"buscador-{uuid.uuid4().hex[:12]}"
    tmp = d / f"tmp-{cid}.json"
    tmp.write_text(json.dumps({"id": cid, "script": script, "timeoutMs": int(timeout * 1000)}), encoding="utf-8")
    os.replace(tmp, d / f"command-{cid}.json")  # o painel só vê o arquivo já completo
    resp = d / f"response-{cid}.json"
    end = time.time() + timeout
    while time.time() < end:
        if resp.exists():
            try:
                data = json.loads(resp.read_text(encoding="utf-8"))
            except ValueError:
                time.sleep(0.1)
                continue
            resp.unlink(missing_ok=True)
            if not data.get("success"):
                raise RuntimeError(data.get("error") or "o Premiere recusou o comando")
            return str(data.get("result", ""))
        time.sleep(0.15)
    (d / f"command-{cid}.json").unlink(missing_ok=True)
    raise TimeoutError("O Premiere não respondeu a tempo (ele pode estar ocupado com uma janela aberta).")


def _js(value) -> str:
    """Valor Python → literal ExtendScript (ES3: só strings e números)."""
    return json.dumps(value, ensure_ascii=True)


def status() -> dict:
    try:
        out = run("(function(){ if (!app.project || !app.project.path) return 'SEM'; "
                  "return 'OK|' + app.project.name; })()", timeout=10)
    except Exception as exc:
        return {"connected": False, "message": str(exc)}
    if out.startswith("OK|"):
        return {"connected": True, "project": out[3:]}
    return {"connected": False, "message": "O Premiere está aberto, mas sem nenhum projeto."}


# Funções auxiliares rodadas dentro do Premiere
_HELPERS = r"""
function __bin(name) {
  var root = app.project.rootItem;
  for (var i = 0; i < root.children.numItems; i++) {
    var c = root.children[i];
    if (c && c.type == 2 && c.name == name) return c;
  }
  var b = root.createBin(name);
  if (b) return b;
  for (var j = 0; j < root.children.numItems; j++) {
    var d = root.children[j];
    if (d && d.type == 2 && d.name == name) return d;
  }
  return root;
}
function __norm(p) { return String(p).replace(/\//g, "\\").toLowerCase(); }
function __find(bin, path) {
  var want = __norm(path);
  for (var i = bin.children.numItems - 1; i >= 0; i--) {
    var c = bin.children[i];
    try { if (c && c.type == 1 && __norm(c.getMediaPath()) == want) return c; } catch (e) {}
  }
  return null;
}
function __time(sec) { var t = new Time(); t.seconds = sec; return t; }
"""


def import_files(paths: list[str], bin_name: str, subclips: list[dict] | None = None) -> dict:
    """Importa arquivos numa pasta (bin) do projeto aberto. `subclips`: [{path, name, start, end}] em segundos
    — cria um subclipe já cortado no trecho (usado para frases encontradas na fala)."""
    subclips = subclips or []
    script = _HELPERS + f"""
(function() {{
  if (!app.project || !app.project.path) return "ERRO|Abra um projeto no Premiere primeiro.";
  var paths = {_js(paths)};
  var subs = {_js(subclips)};
  var bin = __bin({_js(bin_name)});
  var fresh = [];  // não importa de novo o que já está nesta pasta do projeto
  for (var k = 0; k < paths.length; k++) if (!__find(bin, paths[k])) fresh.push(paths[k]);
  var before = bin.children.numItems;
  if (fresh.length) app.project.importFiles(fresh, true, bin, false);
  var imported = bin.children.numItems - before;
  var made = 0, failed = 0;
  for (var i = 0; i < subs.length; i++) {{
    var s = subs[i];
    var item = __find(bin, s.path);
    if (!item) {{ failed++; continue; }}
    var clip = null;
    try {{ clip = item.createSubClip(s.name, __time(s.start), __time(s.end), 0, 1, 1); }} catch (e1) {{}}
    if (!clip) {{
      try {{ clip = item.createSubClip(s.name, String(Math.round(s.start * {TICKS_PER_SECOND})),
                                       String(Math.round(s.end * {TICKS_PER_SECOND})), 0, 1, 1); }} catch (e2) {{}}
    }}
    if (clip) {{ try {{ clip.moveBin(bin); }} catch (e3) {{}} made++; }} else failed++;
  }}
  return "OK|" + imported + "|" + made + "|" + failed + "|" + app.project.name;
}})()
"""
    out = run(script, timeout=300)
    if out.startswith("ERRO|"):
        raise RuntimeError(out[5:])
    _, imported, made, failed, project = out.split("|", 4)
    return {"imported": int(imported), "subclips": int(made), "subclips_failed": int(failed), "project": project,
            "bin": bin_name}
