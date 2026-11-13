<p align="center"><img src="logo/BuscadorFAST-logo-para-fundo-claro.png" alt="BuscadorFAST" width="440"></p>

<p align="center"><b>Encontre qualquer foto ou vídeo em todos os seus discos pelo conteúdo.</b><br>
O que aparece na imagem, as pessoas, o texto escrito, o que é falado e os sons. Tudo roda no seu computador: nada vai para a nuvem.</p>

---

## Instalar (Windows)

1. Baixe o **BuscadorFAST-Instalador-x.y.z.exe** na página de versões (**Releases**, à direita).
2. Abra o arquivo. Como o instalador não tem assinatura digital paga, o Windows pode avisar *"O Windows protegeu o computador"*: clique em **Mais informações → Executar assim mesmo**.
3. Siga o assistente (**Avançar → Instalar**). No fim, uma janela preta prepara o Python e a inteligência artificial. São alguns gigabytes: leva de 10 a 40 minutos, conforme a internet.
4. Abra o **BuscadorFAST** pelo atalho e vá em **Ferramentas → Indexar discos**.

Para atualizar, rode o instalador da versão nova por cima: o catálogo é mantido. Para remover, use **Configurações → Aplicativos** do Windows (ele pergunta se apaga o catálogo; suas fotos e vídeos nunca são apagados).

### Requisitos

| | |
|---|---|
| Sistema | Windows 10 ou 11, 64 bits |
| Memória | 16 GB de RAM (com 8 GB funciona, mais devagar) |
| Espaço | uns 15 GB para o programa e os modelos de IA, mais o catálogo (miniaturas de cada foto e vídeo) |
| Placa de vídeo | NVIDIA RTX com 8 GB ou mais, recomendada. Sem ela, a IA roda no processador, bem mais devagar |
| Internet | na instalação e na primeira vez em que cada recurso de IA é usado |

## O que ele faz

- **Busca por descrição**, em português: "criança na praia", "bolo de aniversário", "palco com público".
- **Pessoas**: reconhece rostos, junta os da mesma pessoa e acha as fotos em que duas ou mais aparecem juntas. Também busca alguém a partir de uma foto.
- **Texto escrito na foto** (faixas, placas, documentos), **fala dos vídeos** (transcrição com o trecho exato) e **sons** (aplausos, música, fogos…).
- **Descrição automática** de cada foto e vídeo, que também entra na busca.
- **Muitos discos**, inclusive desconectados: o catálogo continua mostrando as miniaturas e avisa qual disco ligar.
- **Linha do tempo, mapa, álbuns automáticos, favoritos e coleções.**
- **Duplicados** (libera espaço com lixeira própria), **fotos ruins para revisar** e **saúde dos discos**.
- **Premiere e Lightroom**: envia arquivos para o projeto aberto no Premiere e grava palavras-chave em XMP.
- **Pelo celular**, na mesma rede Wi-Fi ou de qualquer lugar com o Tailscale, protegido por chave.

O manual completo está no [LEIAME.md](LEIAME.md).

## Como funciona

Um servidor local em Python (FastAPI) guarda o catálogo num banco SQLite e mostra a tela no navegador, em `http://127.0.0.1:8765`. A indexação roda em três frentes ao mesmo tempo (imagem, áudio e texto), usando a placa de vídeo quando existe.

| Recurso | Modelo | Licença |
|---|---|---|
| Palavras-chave e busca por imagem | [SigLIP 2](https://huggingface.co/google/siglip2-so400m-patch14-384) (Google) | Apache 2.0 |
| Descrição das fotos | [Qwen2.5-VL-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct) (Alibaba) | Qwen Research License: uso não comercial |
| Rostos | [InsightFace buffalo_l](https://github.com/deepinsight/insightface) | uso não comercial e de pesquisa |
| Fala dos vídeos | [Whisper large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) via faster-whisper | MIT |
| Sons | [AST AudioSet](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593) (MIT) | BSD-3-Clause |
| Texto nas fotos | [EasyOCR](https://github.com/JaidedAI/EasyOCR) | Apache 2.0 |

Os modelos não fazem parte deste repositório: o instalador baixa cada um da fonte oficial. Dois deles (rostos e descrição) são liberados só para uso **não comercial**.

## Privacidade

O catálogo (palavras-chave, nomes das pessoas, transcrições, miniaturas) fica na pasta `data` do programa, no seu computador. Nada é enviado para fora: a internet só é usada para baixar o programa e os modelos. O acesso pelo celular exige uma chave secreta gerada no seu PC.

## Para desenvolvedores

```powershell
# preparar o ambiente a partir do código (baixa Python, bibliotecas e o modelo de rostos)
powershell -ExecutionPolicy Bypass -File instalador\configurar.ps1

# abrir
.venv\Scripts\python.exe -m buscador abrir

# montar o instalador (precisa do Inno Setup 6: winget install JRSoftware.InnoSetup)
instalador\montar.bat 1.0.1
```

- `buscador/`: o servidor e a IA (Python)
- `web/`: a tela (HTML, CSS e JavaScript, sem framework)
- `launcher/`: o `BuscadorFAST.exe` (C#), o ícone e a atualização noturna
- `instalador/`: o assistente (Inno Setup) e o script que prepara Python, bibliotecas e modelos
- `logo/`: a logo e o gerador dos ícones (`launcher/make_icon.py`)
