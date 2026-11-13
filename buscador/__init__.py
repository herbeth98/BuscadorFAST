"""BuscadorFAST: encontra fotos e vídeos em todos os discos pelo conteúdo."""
import os
from pathlib import Path

# Instalado pelo instalador: os modelos de IA ficam dentro da pasta do programa (models\hf), e não na pasta
# do usuário. Num PC que já tinha os modelos no lugar padrão (sem models\hf), nada muda.
_MODELS = Path(__file__).resolve().parent.parent / "models"
if (_MODELS / "hf").is_dir():
    os.environ.setdefault("HF_HOME", str(_MODELS / "hf"))
    os.environ.setdefault("EASYOCR_MODULE_PATH", str(_MODELS / "easyocr"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
