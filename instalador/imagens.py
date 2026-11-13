"""Imagens do assistente de instalação (Inno Setup), feitas a partir do ícone em logo\\.

Uso: python instalador\\imagens.py <pasta de saída>
"""
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
ICONE = Image.open(RAIZ / "logo" / "BuscadorFAST-icone-1024.png").convert("RGBA")
FUNDO = (245, 245, 247)       # o "parchment" do app
ESCALAS = {"100": 1.0, "125": 1.25, "150": 1.5, "200": 2.0, "250": 2.5}


def bmp(tamanho, lado_icone, centro_y, saida):
    img = Image.new("RGB", tamanho, FUNDO)
    ic = ICONE.resize((lado_icone, lado_icone), Image.LANCZOS)
    img.paste(ic, ((tamanho[0] - lado_icone) // 2, int(centro_y - lado_icone / 2)), ic)
    img.save(saida, "BMP")


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for nome, k in ESCALAS.items():
        # imagem grande da esquerda (boas-vindas e fim): 164 x 314 em 100%
        w, h = round(164 * k), round(314 * k)
        bmp((w, h), round(96 * k), h * 0.36, out / f"assistente-{nome}.bmp")
        # imagem pequena do canto (demais páginas): 55 x 58 em 100%
        w, h = round(55 * k), round(58 * k)
        bmp((w, h), round(50 * k), h / 2, out / f"icone-{nome}.bmp")
    print(out)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
