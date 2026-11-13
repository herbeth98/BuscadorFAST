"""Baixa de uma vez todos os modelos de IA (o instalador usa isto).

Sem isso, cada modelo é baixado na primeira vez em que é usado. Rodar de novo só confere: o que já foi
baixado não é baixado outra vez.
"""
import sys
import urllib.request
from pathlib import Path

from .config import MODEL_NAME, ROOT

FACES_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
# pesos em outros formatos que o programa não usa (quando o modelo também tem .safetensors)
_OUTROS_FORMATOS = ["*.bin", "*.pt", "*.pth", "*.h5", "*.msgpack", "*.ot", "*.onnx", "*.tflite", "*.gguf",
                    "flax_model*", "tf_model*", "onnx/*", "openvino/*"]


def _hf(repo: str) -> None:
    from huggingface_hub import HfApi, snapshot_download
    arquivos = HfApi().list_repo_files(repo)
    ignorar = _OUTROS_FORMATOS if any(a.endswith(".safetensors") for a in arquivos) else None
    snapshot_download(repo, ignore_patterns=ignorar)


def _rostos() -> None:
    destino = ROOT / "models" / "buffalo_l.zip"
    if destino.exists() and destino.stat().st_size > 250e6:
        print("   já baixado")
        return
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".zip.parcial")

    def progresso(blocos, tam, total):
        if total > 0:
            feito = min(blocos * tam, total)
            sys.stdout.write(f"\r   {feito / 1e6:,.0f} de {total / 1e6:,.0f} MB".replace(",", "."))
            sys.stdout.flush()

    urllib.request.urlretrieve(FACES_URL, parcial, progresso)
    parcial.replace(destino)
    print()


def baixar_tudo() -> None:
    from . import descricao, som, speech
    passos = [
        ("Rostos (InsightFace buffalo_l, 288 MB)", _rostos),
        (f"Palavras-chave e busca por imagem ({MODEL_NAME})", lambda: _hf(MODEL_NAME)),
        (f"Descrição das fotos ({descricao.MODEL}, cerca de 7,5 GB)", lambda: _hf(descricao.MODEL)),
        (f"Sons dos vídeos ({som.MODEL})", lambda: _hf(som.MODEL)),
        (f"Fala dos vídeos (Whisper {speech.MODEL})", lambda: __import__("faster_whisper").download_model(speech.MODEL)),
        ("Texto escrito nas fotos (EasyOCR)", lambda: __import__("easyocr").Reader(["pt", "en"], gpu=False, verbose=False)),
    ]
    falhas = []
    for i, (nome, baixar) in enumerate(passos, 1):
        print(f"\n[{i}/{len(passos)}] {nome}", flush=True)
        try:
            baixar()
        except Exception as e:  # noqa: BLE001  um modelo que falhar é baixado depois, no primeiro uso
            falhas.append(nome)
            print(f"   não deu certo agora ({e}); ele será baixado no primeiro uso.")
    print("\nModelos prontos." if not falhas else f"\nFicaram para depois: {', '.join(falhas)}.")
