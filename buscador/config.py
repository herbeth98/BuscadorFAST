"""Caminhos e constantes do BuscadorFAST."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "catalogo.db"
THUMB_DIR = DATA_DIR / "thumbs"
WEB_DIR = ROOT / "web"

THUMB_SIZE = 448  # lado maior da miniatura; a IA também lê dela (funciona com o disco offline)

RAW_EXT = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raf", ".orf", ".rw2", ".pef", ".srw", ".nrw"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff", ".bmp", ".gif"} | RAW_EXT
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".mts", ".m2ts", ".wmv", ".webm", ".3gp", ".mpg", ".mpeg"}

# Pastas que nunca entram no índice
SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "program files",
    "program files (x86)", "programdata", "appdata", "node_modules", ".git",
    "$windows.~bt", "$windows.~ws", "recovery", "msocache", "__pycache__", ".venv",
    # jogos e lojas de apps: milhares de texturas e ícones que não são fotos
    "windowsapps", "xboxgames", "steamlibrary", "steamapps", "riot games", "epic games", "ea games",
    "ea sports fc 27", "origin games", "gog games", "ubisoft game launcher", "curseforge",
    "euro truck simulator 2", "american truck simulator", "my games", "rockstar games", "steam",
    # programas que guardam imagens próprias (modelos, ícones, prévias)
    "corel", "corel content", "adobe", "microsoft", "google", "nvidia", "amd", "intel", "drivers",
    # IA e programação: modelos, ambientes Python, caches
    "comfyui", "custom_nodes", "stable-diffusion-webui", "stable diffusion", "invokeai", "fooocus", "pinokio",
    "ollama", "lm studio", ".cache", "huggingface", "site-packages", "dist-packages", "venv", "env",
    "miniconda3", "anaconda3", ".conda", ".vscode", ".idea", "dist", "build",
    # dados do próprio programa e a lixeira de duplicados
    "buscadorfast", "buscadorfast-lixeira", "buscadorfast-backup",
}
# Pastas que começam assim também ficam de fora (instaladores, drivers baixados…)
SKIP_PREFIXES = ("instalador", "installer", "setup ", "drivers ")
# Uma pasta com um destes arquivos é um projeto de software (código, IA): fica de fora com tudo dentro.
# package.json NÃO entra: os projetos do HyperFrames têm um, e os renders lá dentro são vídeos seus.
CODE_MARKERS = (".git", "pyproject.toml", "requirements.txt", "setup.py", "cargo.toml", "go.mod", "pom.xml")


def skip_dir_name(name: str) -> bool:
    n = name.lower()
    return n in SKIP_DIRS or n.startswith(".") or n.startswith(SKIP_PREFIXES)


def is_code_project(path) -> bool:
    import os
    return any(os.path.exists(os.path.join(path, m)) for m in CODE_MARKERS)

MIN_IMAGE_BYTES = 20 * 1024  # ignora ícones e imagens minúsculas
# Quadros exportados de animação/edição (0001.png, 0002.png…) não são fotos
SEQUENCE_EXT = {".png", ".tif", ".tiff", ".tga", ".exr", ".dpx"}


def is_sequence_frame(name: str) -> bool:
    """0217.png ou "LOGO NOVA_00002.png" (numeração com zeros à esquerda) — não pega IMG_1764.PNG do iPhone."""
    import re
    stem, _, ext = name.rpartition(".")
    if f".{ext.lower()}" not in SEQUENCE_EXT:
        return False
    return stem.isdigit() or re.search(r"_0\d{4,}$", stem) is not None

# Modelo de IA: SigLIP 2 é multilíngue, então entende buscas em português.
MODEL_NAME = "google/siglip2-so400m-patch14-384"
TAG_THRESHOLD = 0.08      # probabilidade mínima para virar palavra-chave
MAX_TAGS_PER_FILE = 12
AI_BATCH = 32
