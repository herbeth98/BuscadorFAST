"""Gera a logo do BuscadorFAST e todos os ícones a partir do mesmo desenho.

Símbolo: lupa branca sobre o azul de ação do app. Dentro da lente, uma paisagem (as fotos) e um brilho
(a IA que acha). Duas versões do mesmo desenho:
  · completa (paisagem + brilhos), para 48 px ou mais;
  · simples (só o brilho), para 32 px ou menos, onde os detalhes virariam borrão.

Saídas:
  web/icone.svg, web/icone-simples.svg   topo do app e favicon
  web/icone-180.png                      tela de início do iPhone (quadrado cheio: o iOS arredonda)
  web/icone-192.png, web/icone-512.png   Android e atalhos
  web/favicon-32.png                     favicon para navegadores sem SVG
  launcher/icone.ico, launcher/icone.png ícone do BuscadorFAST.exe (depois rode compilar.bat)
  logo/                                  arquivos-mestre: SVG, PNG 1024, logo com o nome (fundo transparente)
                                         e uma folha de apresentação

Uso:  .venv\\Scripts\\python.exe launcher\\make_icon.py            (gera tudo)
      .venv\\Scripts\\python.exe launcher\\make_icon.py previa.png (só uma prévia, para ajustar o desenho)
Precisa do Google Chrome (desenha o SVG e a fonte) e de internet (fonte Inter, do Google Fonts).
"""
import io
import math
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WEB, LOGO, LAUNCHER = ROOT / "web", ROOT / "logo", ROOT / "launcher"
CHROME = next(p for p in (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                          Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
                          Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")) if p.exists())
FONT = "https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,300..700&display=block"

S = 1024          # tela do desenho
C = 445           # centro da lente: lente + cabo ficam centralizados no quadrado
DIAG = math.sqrt(0.5)

# fundo: o azul de ação do app, um pouco mais claro em cima
FUNDO = (("0", "#4aa8ff"), (".52", "#1680f0"), ("1", "#0057c6"))


def at(dist):
    """Ponto na diagonal do cabo, a `dist` do centro da lente."""
    return C + dist * DIAG


def sparkle(x, y, r, k=0.12):
    """Brilho de quatro pontas (o "✦" que hoje indica IA)."""
    q = r * k
    return (f"M{x:.1f} {y - r:.1f}Q{x + q:.1f} {y - q:.1f} {x + r:.1f} {y:.1f}"
            f"Q{x + q:.1f} {y + q:.1f} {x:.1f} {y + r:.1f}"
            f"Q{x - q:.1f} {y + q:.1f} {x - r:.1f} {y:.1f}"
            f"Q{x - q:.1f} {y - q:.1f} {x:.1f} {y - r:.1f}Z")


def squircle(size=S, n=5.0, steps=720):
    """Contorno dos ícones da Apple: superelipse (|x|^n + |y|^n = 1), sem a quina do retângulo arredondado."""
    a = c = size / 2
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        ct, st = math.cos(t), math.sin(t)
        pts.append((c + a * math.copysign(abs(ct) ** (2 / n), ct), c + a * math.copysign(abs(st) ** (2 / n), st)))
    return pts


def svg(simples=False, arredondado=True):
    """O símbolo em SVG. `arredondado=False` dá o quadrado cheio (para o iPhone e para gerar os PNG)."""
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in FUNDO)
    forma = "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in squircle()) + "Z"
    if simples:
        ring_r, ring_w, cabo_w, cabo_fim = 200, 92, 120, 452
        dentro = f'<path d="{sparkle(C, C, 82)}"/>'
        sombra, filtro = "", ""
    else:
        ring_r, ring_w, cabo_w, cabo_fim = 210, 68, 92, 470
        serra = [(-170, 96), (-52, -30), (6, 28), (58, -14), (170, 92), (170, 210), (-170, 210)]
        serra_d = "M" + "L".join(f"{C + x} {C + y}" for x, y in serra) + "Z"
        dentro = (f'<g clip-path="url(#lente)"><path d="{serra_d}" stroke="#fff" stroke-width="14" stroke-linejoin="round"/></g>'
                  f'<path d="{sparkle(C + 66, C - 80, 44)}"/>'
                  f'<path d="{sparkle(C + 2, C - 116, 17)}"/>')
        sombra = ('<filter id="sombra" x="-30%" y="-30%" width="160%" height="160%">'
                  '<feDropShadow dx="0" dy="12" stdDeviation="16" flood-color="#00265e" flood-opacity=".30"/></filter>')
        filtro = ' filter="url(#sombra)"'
    # a versão completa fica um pouco menor, com mais respiro (como nos ícones da Apple); a simples ocupa mais
    escala = 1 if simples else 0.92
    corpo = (f'<rect width="{S}" height="{S}" fill="url(#fundo)"/>'
             f'<g fill="#fff"{filtro} transform="translate({S / 2} {S / 2}) scale({escala}) translate({-S / 2} {-S / 2})">'
             f'<circle cx="{C}" cy="{C}" r="{ring_r}" fill="none" stroke="#fff" stroke-width="{ring_w}"/>'
             f'<path d="M{at(236):.1f} {at(236):.1f}L{at(cabo_fim):.1f} {at(cabo_fim):.1f}" stroke="#fff" '
             f'stroke-width="{cabo_w}" stroke-linecap="round"/>'
             f'{dentro}</g>')
    if arredondado:
        corpo = f'<g clip-path="url(#forma)">{corpo}</g>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}">'
            f'<title>BuscadorFAST</title><defs>'
            f'<linearGradient id="fundo" x1="0" y1="0" x2=".32" y2="1">{stops}</linearGradient>'
            f'<clipPath id="lente"><circle cx="{C}" cy="{C}" r="156"/></clipPath>'
            f'<clipPath id="forma"><path d="{forma}"/></clipPath>{sombra}</defs>{corpo}</svg>')


# ---------------------------------------------------------------- desenhar com o Chrome
def chrome(html, w, h, tmp, name):
    page = tmp / f"{name}.html"
    page.write_text(html, encoding="utf-8")
    out = tmp / f"{name}.png"
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                    f"--user-data-dir={tmp / 'perfil'}", f"--window-size={w},{h}", "--virtual-time-budget=6000",
                    f"--screenshot={out}", page.as_uri()], capture_output=True, timeout=180)
    return Image.open(out).convert("RGB")


def render_icon(simples, tmp):
    """PNG 1024 com o contorno arredondado transparente."""
    name = "simples" if simples else "completo"
    (tmp / f"{name}.svg").write_text(svg(simples, arredondado=False), encoding="utf-8")
    cheio = chrome(f'<html><body style="margin:0"><img src="{name}.svg" style="display:block;width:{S}px;height:{S}px">'
                   f'</body></html>', S, S, tmp, name)
    big = S * 4
    m = Image.new("L", (big, big), 0)
    ImageDraw.Draw(m).polygon([(x * 4, y * 4) for x, y in squircle(steps=2048)], fill=255)
    rgba = cheio.convert("RGBA")
    rgba.putalpha(m.resize((S, S), Image.LANCZOS))
    return cheio, rgba


def lockup(cor, tmp, name, icone="icone.svg"):
    """Símbolo + nome, com fundo transparente (desenha sobre branco e sobre preto e separa o fundo)."""
    def page(bg):
        return (f'<!doctype html><html><head><link rel="stylesheet" href="{FONT}"><style>'
                f'html,body{{margin:0;background:{bg}}}'
                f'.l{{display:inline-flex;align-items:center;gap:34px;padding:64px;font:300 132px/1 Inter;'
                f'letter-spacing:-.035em;color:{cor};font-optical-sizing:auto}}'
                f'.l img{{width:172px;height:172px;display:block}}.l b{{font-weight:700;letter-spacing:-.012em}}'
                f'</style></head><body><div class="l"><img src="{icone}" alt=""><span>Buscador<b>FAST</b></span></div>'
                f'</body></html>')
    w = np.asarray(chrome(page("#ffffff"), 1500, 320, tmp, name + "-b"), dtype=np.float64) / 255
    k = np.asarray(chrome(page("#000000"), 1500, 320, tmp, name + "-p"), dtype=np.float64) / 255
    a = np.clip(1 - (w - k).mean(axis=2), 0, 1)
    col = np.where(a[..., None] > 1e-4, k / np.maximum(a[..., None], 1e-4), 0)
    rgba = np.dstack([np.clip(col, 0, 1) * 255, a * 255]).round().astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")
    box = img.getchannel("A").point(lambda v: 255 if v > 3 else 0).getbbox()
    pad = 24
    return img.crop((box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))


def write_ico(path, images):
    """ICO com uma imagem PNG por tamanho (aceito pelo Windows e pelo compilador do .exe)."""
    blobs = []
    for im in images:
        b = io.BytesIO()
        im.save(b, "PNG")
        blobs.append((im.size, b.getvalue()))
    offset = 6 + 16 * len(blobs)
    head, data = struct.pack("<HHH", 0, 1, len(blobs)), b""
    for (w, h), blob in blobs:
        head += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    path.write_bytes(head + data)


def sheet(tmp, out):
    """Folha de apresentação: símbolo grande, logo no claro e no escuro, tamanhos reais."""
    html = f'''<!doctype html><html><head><link rel="stylesheet" href="{FONT}"><style>
      *{{box-sizing:border-box}} html,body{{margin:0}}
      body{{width:1600px;height:1000px;font-family:Inter;background:#f5f5f7;color:#1d1d1f;display:grid;
        grid-template-columns:620px 1fr;grid-template-rows:1fr 1fr 230px;}}
      .hero{{grid-row:1/3;display:grid;place-items:center;}}
      .hero img{{width:400px;height:400px;filter:drop-shadow(3px 5px 30px rgba(0,0,0,.22))}}
      .lk{{display:flex;align-items:center;justify-content:center;gap:18px;font:300 64px/1 Inter;letter-spacing:-.035em}}
      .lk img{{width:84px;height:84px}} .lk b{{font-weight:700;letter-spacing:-.012em}}
      .claro{{background:#fff}} .escuro{{background:#000;color:#f5f5f7}}
      .sizes{{grid-column:1/3;display:flex;align-items:flex-end;justify-content:center;gap:56px;padding:0 0 46px;
        background:#f5f5f7;border-top:1px solid rgba(0,0,0,.08)}}
      .sz{{display:flex;flex-direction:column;align-items:center;gap:12px;font-size:13px;color:#6e6e73}}
      .sz img{{display:block}}
      .fav{{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid rgba(0,0,0,.08);border-radius:10px;
        padding:8px 14px 8px 10px;font-size:14px;color:#1d1d1f}}
      .phone{{width:88px;height:88px;border-radius:20px;overflow:hidden}}
    </style></head><body>
      <div class="hero"><img src="completo-r.svg" alt=""></div>
      <div class="lk claro"><img src="completo-r.svg" alt=""><span>Buscador<b>FAST</b></span></div>
      <div class="lk escuro"><img src="completo-r.svg" alt=""><span>Buscador<b>FAST</b></span></div>
      <div class="sizes">
        <div class="sz"><img class="phone" src="completo-q.svg" alt="">iPhone</div>
        <div class="sz"><img src="completo-r.svg" width="64" height="64" alt="">64 px</div>
        <div class="sz"><img src="completo-r.svg" width="48" height="48" alt="">48 px</div>
        <div class="sz"><img src="simples-r.svg" width="32" height="32" alt="">32 px</div>
        <div class="sz"><img src="simples-r.svg" width="16" height="16" alt="">16 px</div>
        <div class="sz"><span class="fav"><img src="simples-r.svg" width="16" height="16" alt="">BuscadorFAST</span>aba do navegador</div>
      </div></body></html>'''
    for simples in (False, True):
        n = "simples" if simples else "completo"
        (tmp / f"{n}-r.svg").write_text(svg(simples, True), encoding="utf-8")
        (tmp / f"{n}-q.svg").write_text(svg(simples, False), encoding="utf-8")
    chrome(html, 1600, 1000, tmp, "folha").save(out)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="logo-"))
    try:
        if len(sys.argv) > 1:          # só a prévia
            sheet(tmp, Path(sys.argv[1]))
            print(sys.argv[1])
            return
        LOGO.mkdir(exist_ok=True)
        # SVG
        (WEB / "icone.svg").write_text(svg(False, True), encoding="utf-8")
        (WEB / "icone-simples.svg").write_text(svg(True, True), encoding="utf-8")
        (LOGO / "BuscadorFAST-icone.svg").write_text(svg(False, True), encoding="utf-8")
        (LOGO / "BuscadorFAST-icone-quadrado.svg").write_text(svg(False, False), encoding="utf-8")
        # PNG
        cheio, completo = render_icon(False, tmp)
        _, simples = render_icon(True, tmp)
        size = lambda im, s: im.resize((s, s), Image.LANCZOS)
        completo.save(LOGO / "BuscadorFAST-icone-1024.png")
        size(cheio, 180).save(WEB / "icone-180.png")
        size(completo, 192).save(WEB / "icone-192.png")
        size(completo, 512).save(WEB / "icone-512.png")
        size(simples, 32).save(WEB / "favicon-32.png")
        size(completo, 256).save(LAUNCHER / "icone.png")
        write_ico(LAUNCHER / "icone.ico", [size(simples, s) for s in (16, 20, 24, 32, 40)]
                  + [size(completo, s) for s in (48, 64, 96, 128, 256)])
        shutil.copy(LAUNCHER / "icone.ico", LOGO / "BuscadorFAST.ico")
        # logo com o nome (fundo transparente) e folha de apresentação
        (tmp / "icone.svg").write_text(svg(False, True), encoding="utf-8")
        lockup("#1d1d1f", tmp, "claro").save(LOGO / "BuscadorFAST-logo-para-fundo-claro.png")
        lockup("#f5f5f7", tmp, "escuro").save(LOGO / "BuscadorFAST-logo-para-fundo-escuro.png")
        sheet(tmp, LOGO / "BuscadorFAST-apresentacao.png")
        print("ok:", LOGO)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
