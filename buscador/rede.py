"""Acesso pelo celular: na mesma rede Wi-Fi ou de qualquer lugar pelo Tailscale.

O programa normal escuta só no próprio PC (127.0.0.1:8765). Com o acesso ligado, um segundo servidor
escuta na rede (porta 8766) e só atende quem tiver a chave (que vai no QR code). Ações que mexem nos
arquivos ou no PC ficam bloqueadas para o celular.
"""
import json
import secrets
import socket
import threading

from .config import DATA_DIR

SETTINGS = DATA_DIR / "rede.json"
PORT = 8766
PORT_SECURE = 8767   # https: o celular só libera o microfone (busca por voz) em conexão segura
# Entrada do HTTPS do Tailscale ("tailscale serve"). Ele repassa os pedidos a partir do próprio PC (127.0.0.1);
# por isso esta porta escuta só no PC e é tratada sempre como celular: pede a chave e bloqueia as mesmas ações.
PORT_PROXY = 8768
COOKIE = "bf_chave"

# Pelo celular não: apagar/mover arquivos, abrir coisas no PC, fechar o programa, mudar configurações
BLOCKED = (
    "/api/sair", "/api/open/", "/api/lixeira/esvaziar", "/api/lixeira/restaurar", "/api/duplicados/lixeira",
    "/api/backup/config", "/api/rede", "/api/scan", "/api/cancel", "/api/xmp",
    "/api/transferir/destino", "/api/transferir/abrir-pasta", "/api/transferir/escolher", "/api/atualizar",
    "/api/pendentes", "/api/agenda", "/api/revisar/lixeira", "/api/leitura",
)

_server = None
_thread = None
_lock = threading.Lock()


def settings() -> dict:
    try:
        return {"enabled": False, "token": "", **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except (FileNotFoundError, ValueError):
        return {"enabled": False, "token": ""}


def _save(s: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")


def local_ip() -> str:
    """IP do PC na rede local (não envia nada: só pergunta ao Windows qual placa usaria)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def url(s: dict | None = None, secure: bool = True) -> str:
    s = s or settings()
    proto, port = ("https", PORT_SECURE) if secure else ("http", PORT)
    return f"{proto}://{local_ip()}:{port}/?chave={s['token']}"


def qr_svg(text: str) -> str:
    import io

    import qrcode
    import qrcode.image.svg

    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def _certificate() -> tuple[str, str]:
    """Certificado próprio (autoassinado) para o endereço seguro. Refaz se o IP do PC mudar."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    ip = local_ip()
    cert_path, key_path = DATA_DIR / "rede-cert.pem", DATA_DIR / "rede-chave.pem"
    stamp = DATA_DIR / "rede-cert.ip"
    if cert_path.exists() and key_path.exists() and stamp.exists() and stamp.read_text() == ip:
        return str(cert_path), str(key_path)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "BuscadorFAST")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip)),
                                                        x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    stamp.write_text(ip)
    return str(cert_path), str(key_path)


def start(app) -> None:
    """Dois endereços na rede: o normal (http, porta 8766) e o seguro (https, 8767), que libera o microfone
    do celular para a busca por voz."""
    global _server, _thread
    import uvicorn

    with _lock:
        if _server is not None:
            return
        servers = [uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="warning")),
                   uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT_PROXY, log_level="warning"))]
        try:
            cert, key = _certificate()
            servers.append(uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT_SECURE, log_level="warning",
                                                         ssl_certfile=cert, ssl_keyfile=key)))
        except Exception:
            pass  # sem o endereço seguro, o resto funciona (só a voz fica indisponível)
        for s in servers:
            threading.Thread(target=s.run, daemon=True, name=f"rede-{s.config.port}").start()
        _server = servers


def stop() -> None:
    global _server, _thread
    with _lock:
        for s in _server or []:
            s.should_exit = True
        _server, _thread = None, None


def enable(app, on: bool) -> dict:
    s = settings()
    if on and not s["token"]:
        s["token"] = secrets.token_urlsafe(9)
    s["enabled"] = on
    _save(s)
    start(app) if on else stop()
    return status()


def new_key() -> dict:
    s = settings()
    s["token"] = secrets.token_urlsafe(9)  # a chave antiga deixa de funcionar
    _save(s)
    return status()


def status() -> dict:
    s = settings()
    out = {"enabled": s["enabled"], "running": bool(_server) and any(x.started for x in _server),
           "port": PORT, "ip": local_ip()}
    if s["enabled"]:
        out["url"] = url(s)                        # seguro: com busca por voz (o QR leva para este)
        out["url_simples"] = url(s, secure=False)  # o antigo, sem voz
        out["qr"] = qr_svg(out["url"])
        out["fora"] = tailscale_status(s)
    return out


def is_local(host: str | None, port: int | None = None) -> bool:
    """Pedido feito no próprio PC. O que chega pela porta do Tailscale não conta, mesmo vindo de 127.0.0.1."""
    return host in ("127.0.0.1", "::1", "localhost") and port != PORT_PROXY


def is_local_request(request) -> bool:
    server = request.scope.get("server") or (None, None)
    return is_local(request.client.host if request.client else None, server[1])


# ---------------------------------------------------------------- fora de casa (Tailscale)

def _tailscale_exe() -> str | None:
    import os
    import shutil
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        p = os.path.join(base, "Tailscale", "tailscale.exe") if base else ""
        if p and os.path.exists(p):
            return p
    return None


def _ts(*args: str, timeout: int = 15) -> tuple[int, str]:
    import subprocess
    exe = _tailscale_exe()
    if not exe:
        return -1, ""
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        out = e.stdout or b""
        return -2, out.decode("utf-8", "replace") if isinstance(out, bytes) else out
    except OSError:
        return -1, ""


def _https_on(dns: str) -> bool:
    """O endereço https://<pc>.ts.net já está ligado e apontando para a porta do BuscadorFAST?"""
    code, out = _ts("serve", "status", "--json")
    if code != 0:
        return False
    try:
        cfg = json.loads(out or "{}")
    except ValueError:
        return False
    for host, web in (cfg.get("Web") or {}).items():
        if host.split(":")[0].rstrip(".") == dns:
            for h in (web.get("Handlers") or {}).values():
                if str(PORT_PROXY) in str(h.get("Proxy", "")):
                    return True
    return False


def tailscale_status(s: dict | None = None) -> dict:
    """Estado do Tailscale e os endereços para usar fora de casa (com a chave, para virar QR code)."""
    s = s or settings()
    if not _tailscale_exe():
        return {"installed": False}
    code, out = _ts("status", "--json")
    try:
        st = json.loads(out) if code == 0 and out.strip().startswith("{") else {}
    except ValueError:
        st = {}
    me = st.get("Self") or {}
    ips = [ip for ip in (me.get("TailscaleIPs") or []) if "." in ip]
    on = st.get("BackendState") == "Running" and bool(ips)
    res = {"installed": True, "running": on, "state": st.get("BackendState") or "parado"}
    if not on:
        return res
    dns = (me.get("DNSName") or "").rstrip(".")
    res.update(ip=ips[0], name=dns, https=bool(dns) and _https_on(dns))
    if res["https"]:
        res["url"] = f"https://{dns}/?chave={s['token']}"   # certificado de verdade: a busca por voz funciona
    else:
        res["url"] = f"http://{ips[0]}:{PORT}/?chave={s['token']}"  # já criptografado pelo próprio Tailscale
    res["qr"] = qr_svg(res["url"])
    return res


def tailscale_https() -> dict:
    """Liga o endereço https://<pc>.ts.net, visível só para os aparelhos da sua conta do Tailscale
    (é o "serve", não o "funnel": nada fica aberto para a internet)."""
    import re
    if not _tailscale_exe():
        return {"ok": False, "error": "O Tailscale não está instalado neste PC."}
    code, out = _ts("serve", "--bg", f"http://127.0.0.1:{PORT_PROXY}", timeout=20)
    link = re.search(r"https://login\.tailscale\.com/\S+", out or "")
    if link:  # a conta ainda não liberou HTTPS/serve: o Tailscale pede um clique no site dele
        return {"ok": False, "enable_url": link.group(0),
                "error": "O Tailscale pede que você libere o HTTPS na sua conta (um clique)."}
    if code != 0:
        return {"ok": False, "error": (out or "não deu certo").strip()[-300:]}
    return {"ok": True, **tailscale_status()}
