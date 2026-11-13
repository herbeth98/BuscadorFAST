# BuscadorFAST

Catálogo de fotos e vídeos de todos os discos, com palavras-chave geradas por IA local (na GPU) e busca por frase livre em português.

## Como usar

**Visual:** inspirado no design system da Apple: fotos em destaque, uma cor de ação só (azul), fonte **Inter** (Google Fonts) e modo claro ou escuro conforme o Windows ou o celular. Sem internet, a fonte volta para a do sistema. A cópia do visual anterior está em `.backup-visual-2026-11-13`.

**Logo:** uma lupa branca sobre o azul do app, com uma paisagem (as fotos) e um brilho (a IA) dentro da lente. Os arquivos ficam na pasta `logo` (SVG, PNG 1024, logo com o nome em fundo transparente para fundo claro e escuro, `.ico` e uma folha de apresentação). O mesmo desenho vira o ícone do atalho, a aba do navegador e o ícone da tela de início do iPhone. Para mudar o desenho: edite `launcher\make_icon.py`, rode `.venv\Scripts\python.exe launcher\make_icon.py` e depois `launcher\compilar.bat` (grava o ícone no `BuscadorFAST.exe`).

Abra pelo atalho **BuscadorFAST** na área de trabalho ou no Menu Iniciar (ou dois cliques em `BuscadorFAST.exe`). O programa roda sem janela e a tela abre no navegador (`http://127.0.0.1:8765`). Abrindo de novo com ele já aberto, só reabre a tela. Para fechar, use o botão **⏻** no canto superior direito.

**No topo:** a busca (tecla **/** leva até ela), uma pílula só com o microfone, a câmera e, no fim, *onde procurar* (em tudo, palavras exatas, escrito na foto, falado, sons). **Pessoas**, **Transferir** e o menu **Ferramentas** (Indexar discos, Duplicados e lixeira, Saúde dos discos). Acima das fotos ficam o total de resultados, o **tipo** (Tudo, Fotos, Vídeos, Prints), Linha do tempo, Mapa, Selecionar e a ordem. Na lateral, que cabe inteira numa tela de 1440×900, ficam as marcações, as pessoas, os discos, as datas rápidas (30 dias, este mês, este ano, ano passado), a câmera e as palavras-chave, com um campo para filtrá-las. Com dois ou mais filtros, aparece *Limpar filtros*. A barra de tarefa fica numa linha só; clique nela para ver as três frentes. No visualizador, as setas ‹ › (ou ← →) passam para o arquivo vizinho.

Se algo der errado ao abrir, veja `data\servidor.log`. O `BuscadorFAST.bat` continua funcionando e mostra uma janela com as mensagens.

- **🔄 Atualizar todos os discos** (dentro de *Indexar discos*): percorre os discos marcados, um depois do outro, procurando arquivos novos, alterados e apagados, e depois faz tudo o que estiver pendente. No C: só a sua pasta de usuário é percorrida; os outros discos, inteiros. Desmarque um disco para tirá-lo da atualização (vale pelo disco, mesmo que a letra mude). Discos desconectados são pulados.
- **Indexar discos** (botão no topo): escolha um disco inteiro ou cole o caminho de uma pasta. Só arquivos novos ou alterados são lidos; depois vêm, em sequência, palavras-chave, rostos, texto nas fotos e fala dos vídeos.
  - **Três frentes ao mesmo tempo**: no *Atualizar* e no *Processar tudo que está pendente*, as etapas rodam em paralelo, e já começam enquanto os discos ainda estão sendo lidos. **Imagens** (Lightroom → palavras-chave → fotos ruins → descrição → rostos), **Áudio** (fala e sons dos vídeos, lidos de uma vez só) e **Texto** (texto nas fotos). A barra de progresso mostra cada frente numa linha. O disco já vai lendo os próximos arquivos enquanto a placa de vídeo trabalha no atual. Fotos praticamente iguais a outra já descrita (rajadas, cópias) ganham a mesma descrição sem passar pelo modelo. Se uma etapa der erro, ela tenta de novo sem parar as outras; depois de três erros seguidos, fica para a próxima vez.
  - **O que ainda falta** (na mesma janela) mostra quantos arquivos aguardam cada etapa. **Processar tudo que está pendente** faz todas, na ordem, só no que falta — use depois de parar uma indexação no meio. "Ainda sem miniatura" precisa de *Indexar* no disco onde os arquivos estão; a fala só é transcrita com o disco conectado.
  - Em *Avançado*: **Refazer palavras-chave da IA de todos os arquivos** (depois de mudar o vocabulário; as suas ficam).
- **Buscar**: digite uma palavra-chave, um nome de arquivo ou uma frase ("homem segurando carneiro", "pôr do sol na praia").
  - *Inteligente*: junta palavras exatas com a busca por significado da IA.
  - *Só palavras exatas*: nome do arquivo, pasta e palavras-chave.
  - *Falado nos vídeos*: procura no que foi dito (transcrição automática). A miniatura mostra 🗣 e o minuto da fala; ao abrir, o vídeo começa nesse momento e a transcrição aparece ao lado — clique num trecho para pular até ele. No modo *Inteligente*, o que foi falado também entra na busca.
  - *Texto escrito na foto*: procura o que está escrito dentro da imagem (banner, placa, camiseta, documento). Acha trechos, então "dorper" encontra "MISTER DORPER". O texto lido aparece no visualizador, com o trecho buscado em destaque.
- **Ordenar** (ao lado do total de resultados): mais relevantes, data da foto, modificados por último, adicionados ao catálogo por último, nome, tamanho e vídeos mais longos. A escolha fica salva.
- **■ Parar**: aparece na barra de progresso da página inicial enquanto algo está sendo indexado (pela tela ou pela linha de comando). O que já foi feito fica salvo; indexando de novo, continua de onde parou.
- **Filtros** à esquerda: disco, data, câmera e palavras-chave (clique para filtrar). O tipo (fotos, vídeos, prints) fica acima das fotos.
- **Clique numa miniatura** para ver o arquivo, as palavras-chave e os metadados. Lá você:
  - remove uma palavra-chave errada (×) — a IA não volta a colocá-la nesse arquivo;
  - adiciona as suas (verde) — digite e aperte Enter;
  - abre o arquivo, mostra na pasta ou acha fotos parecidas.
  - Setas ← → passam para o próximo resultado; Esc fecha.
- **Ctrl+clique / Shift+clique** seleciona vários arquivos para adicionar a mesma palavra-chave a todos.

### Pessoas (rostos)

Botão **Pessoas** no topo. A IA encontra os rostos e junta os da mesma pessoa em grupos.

- Em **Rostos sem nome**, digite o nome embaixo do grupo e aperte Enter. Todas as fotos e vídeos dele passam a ser encontrados pelo nome (palavra-chave amarela).
- Usar o mesmo nome em dois grupos junta os dois.
- Clique numa pessoa para ver todos os rostos dela: selecione os errados e use **Não é essa pessoa**, ou **Ignorar** para desconhecidos.
- Rostos novos parecidos com uma pessoa já nomeada recebem o nome sozinhos.
- No visualizador, **Pessoas nesta foto** mostra cada rosto: digite o nome num rosto avulso, ou clique no nome para corrigir.
- **Combinar pessoas:** na janela Pessoas, marque o ✓ no canto de duas ou mais pessoas. Aparece na hora quantas fotos e vídeos a combinação acha. Escolha como combinar:
  - **Juntas:** todas as pessoas marcadas aparecem na mesma foto;
  - **Qualquer uma:** aparece pelo menos uma delas;
  - **Só elas:** juntas, e nenhuma outra pessoa com nome na foto (bom para achar o retrato do casal ou da família, sem as fotos de grupo).

  O filtro fica na lateral, em **Pessoas**: dá para tirar alguém (×), trocar o jeito de combinar e **＋ Adicionar pessoa**. Ele soma com a busca, as datas, os discos, o mapa e a linha do tempo. O filtro é feito pelo rosto, e não pela palavra-chave com o nome.

### Encontrar uma pessoa por foto (📷)

Botão **📷** ao lado da busca (ou arraste/cole uma foto na tela): o programa reconhece o **rosto** da foto enviada e mostra todas as fotos e vídeos em que essa pessoa aparece. Com várias pessoas na foto, usa o maior rosto. A foto enviada não é guardada.

### Categorias e álbuns

- Na lateral: **Tudo · Fotos · Vídeos · Prints** (capturas de tela ficam separadas das fotos).
- **🗂 Álbuns automáticos** (lateral): fotos e vídeos do mesmo dia e lugar (📍 pela localização, 📁 pela pasta), juntando câmera e celular do mesmo evento.
- **🗺 Mapa** (ao lado do total de resultados): o que tem localização, agrupado; *Mostrar só desta área* filtra os resultados.

### O que a IA entende

- **Palavras-chave** de um vocabulário voltado ao seu conteúdo (eventos, prefeitura, São João, agro, esportes…).
- **Descrição em português** de cada foto/vídeo (aparece no visualizador e entra na busca), com palavras-chave livres.
- **Texto escrito** nas fotos, **fala** dos vídeos (Whisper large-v3-turbo, português, filtro de voz), **rostos**.
- Palavras-chave e estrelas que você marcou no **Lightroom** (4–5 estrelas viram ⭐).
- Datas pelo nome do arquivo quando a câmera não gravou a data.

Pastas de sistema, programas, jogos, IA e projetos de software (com `.git`, `requirements.txt`…) ficam fora do catálogo.

### 🔊 Sons dos vídeos

Cada vídeo é "escutado" por uma IA de sons: **aplausos, torcida, multidão, fogos, música, canto, sanfona, percussão, risadas, buzina, sirene, balido, mugido, cavalo, cachorro, chuva** — com o momento em que acontecem e a força (certeza × volume).

- Busque **"aplausos"**, **"fogos"**, **"sanfona"**, **"torcida"**, **"carneiro berrando"**… ou **"momentos altos"** (aplausos + torcida + fogos): os vídeos vêm do momento mais forte para o mais fraco, com 🔊 e o minuto na miniatura, e abrem já no momento.
- Combine com um álbum ou pasta (ex.: o álbum do São João) para ver os picos daquele evento.
- No visualizador, **Sons do vídeo** lista tudo que foi ouvido; toque num som para pular até ele.
- Também há o modo **Sons nos vídeos** no seletor de busca. Precisa do disco do vídeo conectado para ser analisado.

### 📥 Para revisar (fotos ruins)

Na lateral, **📥 Para revisar** junta fotos **borradas**, **escuras demais**, **estouradas** e **repetidas** (rajadas: fica a mais nítida). Nada é movido: use ☑ Selecionar → **✓ Manter** (sai da lista e não volta) ou **🗑 Lixeira** (só no PC; dá para restaurar em Duplicados → Lixeira). Fotos novas entram sozinhas a cada indexação. Os critérios são conservadores: fotos suaves de ensaio não entram.

### 🎤 Busca por voz (celular)

Toque no 🎤, fale ("Maria no São João com a quadrilha") e toque em ■. Quem transcreve é o próprio PC (Whisper), sem mandar sua voz para fora. O celular só libera o microfone no **endereço seguro**: leia o QR code em ⚙ → Acesso pelo celular (na primeira vez, confirme o aviso de "conexão não particular").

### Saúde dos discos

**💽 Saúde dos discos** (lateral, embaixo da lista de discos): temperatura, horas ligado, erros e espaço livre de cada disco, com avisos se algo piorar.

**Teste de leitura:** toda madrugada (depois da atualização) o programa lê os arquivos por até 3 horas, começando pelos testados há mais tempo, e anota os que **não leem** ou que **mudaram sem ninguém mexer** (corrompidos). O progresso de cada disco e a lista de problemas ficam em Saúde dos discos; dá para rodar na hora com *Testar agora*.

### Linha do tempo

Botão **📅 Linha do tempo** ao lado do total de resultados. Mostra quantas fotos e vídeos há em cada **ano**; clique num ano para ver os **meses**, num mês para ver os **dias**, e num dia para ver só ele. Os resultados ficam separados por dia ("quarta-feira, 2 de setembro de 2026"). Para voltar, use o caminho no topo (*Todas as datas › 2026 › setembro*).

- Respeita os filtros: só vídeos, um disco, favoritos, uma coleção, palavras-chave…
- A data é a da foto/gravação (EXIF ou metadados do vídeo). Quando o arquivo não tem essa informação, vale a data de modificação — por isso um dia em que você copiou muitos arquivos pode aparecer como um pico.
- Arquivos ainda não indexados aparecem como "sem data" até a indexação terminar.

### Favoritos e coleções

- **⭐ Favoritar**: passe o mouse na miniatura e clique na estrela, ou use o botão no visualizador (tecla **F**). Para ver só os favoritos, clique em **⭐ Favoritos** na lateral.
- **Coleções** juntam arquivos de qualquer pasta ou disco, sem mover nada (ex.: "Leilão Janeiro 2026").
  - Criar: **＋ Nova coleção** na lateral, ou *Nova coleção…* no menu "Pôr numa coleção".
  - Pôr arquivos: no visualizador ("＋ Pôr numa coleção…") ou selecionando vários (☑ Selecionar → 📁 na barra de baixo).
  - Abrir: clique no nome na lateral. Os arquivos aparecem na ordem em que você foi adicionando.
  - Na coleção aberta: **🎬 Importar coleção no Premiere** (vai para uma pasta com o nome da coleção), **Renomear** e **Excluir coleção**. Excluir apaga só a coleção; os arquivos ficam onde estão.
- Se um duplicado for para a lixeira, a estrela e as coleções dele passam para a cópia que fica.

### Gravar palavras-chave nos arquivos (Lightroom, Bridge, Premiere)

Botão **🏷 Gravar no arquivo**: no visualizador, na barra de seleção ou no cabeçalho de uma coleção. Grava os **nomes das pessoas** e as **palavras-chave que você colocou** no padrão XMP. As da IA só entram se você marcar a opção.

- **JPG, PNG, HEIC, DNG, MP4, MOV**: você escolhe entre *dentro do arquivo* (o Lightroom e o Premiere leem direto) ou *.xmp ao lado* (o original fica intocado).
- **RAW (ARW, CR2, NEF…)**: sempre num `.xmp` ao lado, como o Lightroom faz, acrescentando sem apagar os ajustes do Lightroom.
- **MTS, AVI, MKV**: sempre `.xmp` ao lado.
- A data dos arquivos não muda. Gravar de novo não duplica palavras-chave.
- Precisa do ExifTool (já instalado; para reinstalar: `winget install OliverBetz.ExifTool`).

### Enviar para o Premiere

Com o Premiere aberto num projeto (o painel **MCP Bridge** abre sozinho com ele):

- No visualizador: **🎬 Enviar para o Premiere** importa o arquivo para a pasta (bin) **BuscadorFAST** do projeto.
- Se você buscou uma frase e o vídeo tem a fala: **🎬 Só os trechos falados** importa o vídeo e cria um **subclipe** em cada trecho onde a frase é dita (com 1,5 s de folga antes e depois), pronto para arrastar para a timeline.
- Vários de uma vez: selecione com Ctrl+clique e use **🎬 Premiere** na barra de baixo.
- Quando há uma busca, a pasta no Premiere recebe o nome dela (ex.: "BuscadorFAST - portal da transparência").
- Arquivos que já estão naquela pasta do projeto não são importados de novo.

### Duplicados

Botão **Duplicados** no topo.

1. **Procurar duplicados**: compara os arquivos de mesmo tamanho e confirma lendo o arquivo inteiro. Só arquivos idênticos byte a byte contam. Só discos conectados são conferidos.
2. A lista mostra, do que mais ocupa para o que menos ocupa, cada arquivo com suas cópias. Uma fica marcada como **manter** (verde) e as outras como **remover**. Escolha o disco preferido em *Manter de preferência no disco* ou ajuste cada caixinha. Não dá para marcar todas as cópias de um arquivo.
3. **Mover para a lixeira**: as cópias vão para a pasta `BuscadorFAST-Lixeira` no mesmo disco. Saem das pastas, mas dá para **Restaurar**. Suas palavras-chave passam para a cópia que fica.
4. **Esvaziar e liberar**: apaga de vez a lixeira daquele disco e libera o espaço. Isso não tem volta.

### Vigilância em tempo real

Com o programa aberto, os discos marcados em *Atualizar todos os discos* ficam sendo vigiados:

- Arquivo **apagado** (ou mandado para a Lixeira) sai da busca na hora.
- Arquivo **renomeado ou movido** no mesmo disco é acompanhado e continua com palavras-chave, rostos, estrela e coleções. O mesmo vale para pastas renomeadas.
- Arquivo **novo** entra sozinho no catálogo cerca de 10 segundos depois de terminar de ser copiado, e só ele é processado.
- O que mudar com o programa **fechado**: ao buscar, os resultados que não existem mais somem da tela e saem do catálogo. Para pegar arquivos novos, use *Atualizar todos os discos*.

### Discos desconectados

Por padrão a busca mostra só arquivos de **discos conectados** (caixinha *Só discos conectados* na lateral, marcada). Desmarque para ver também o catálogo de HDs guardados; clicar num disco desconectado na lateral mostra o catálogo dele.

Discos desconectados continuam na busca (bolinha cinza): você vê a miniatura e sabe em que HD e pasta o arquivo está.

## Abrir pelo celular

Em **⚙ → Acesso pelo celular**, marque *Permitir acesso pelo celular* e leia o QR code com a câmera do celular (no mesmo Wi-Fi). O QR leva uma chave secreta: sem ela, ninguém da rede entra. *Gerar nova chave* corta o acesso de quem tinha o QR antigo.

**Fora de casa (Tailscale):** para abrir de qualquer lugar (4G, outro Wi-Fi), na mesma tela aparece a parte *🌎 Fora de casa*.
1. Instale o **Tailscale** no PC ([tailscale.com/download](https://tailscale.com/download)) e no celular (Play Store / App Store), e entre com a **mesma conta** nos dois. É grátis para uso pessoal.
2. Toque em *Verificar de novo*: aparece o QR code de fora de casa. Leia com o celular, com o Tailscale ligado nele.
3. Toque em **🔒 Ligar endereço seguro (HTTPS)**. Na primeira vez, o Tailscale pode pedir que você libere o HTTPS na conta: abra o link, clique em *Enable* e toque no botão de novo. O endereço passa a ser `https://<nome-do-pc>.<sua-rede>.ts.net`, com certificado de verdade: a busca por voz 🎤 funciona e o celular não mostra aviso de segurança.

Só os aparelhos da sua conta do Tailscale enxergam o BuscadorFAST. Nada fica aberto na internet e não é preciso mexer no roteador. A chave do QR e os bloqueios do celular (apagar, mover, configurações) valem igual fora de casa. O PC precisa estar ligado, com o BuscadorFAST aberto e com o acesso pelo celular ligado.

No celular, a navegação fica embaixo, ao alcance do polegar: **Início**, **Filtros** (com o número de filtros ativos), **Pessoas**, **Álbuns** e **Mais** (favoritos, para revisar, transferir, linha do tempo, mapa). Os modos de busca viram botões logo abaixo do campo. O topo se esconde ao rolar para baixo e volta ao rolar para cima. As fotos aparecem 3 por linha, e no visualizador dá para deslizar o dedo para passar de arquivo.

**Baixar para o celular (ou para o PC):** no visualizador, **⬇ Baixar** salva o arquivo original. Em fotos RAW aparece também **⬇ Baixar JPG** (a prévia em alta gravada pela câmera, que abre em qualquer celular). Para vários de uma vez, use ☑ Selecionar → **⬇ Baixar**: eles vêm num `.zip` montado na hora.

**⇄ Transferir** (no topo, no PC e no celular):

- **Do celular para o PC:** no celular, toque em *📷 Fotos e vídeos* ou *📄 Outros arquivos*. Eles chegam em `D:\BuscadorFAST-Recebidos\<data de hoje>` (dá para trocar a pasta no PC), mantêm a data original e as fotos e vídeos entram sozinhos no catálogo — só eles são processados, não a fila inteira.
- **Do PC para o celular:** no PC, *📂 Escolher arquivos no PC* (janela normal do Windows) ou selecione resultados e use *📱 Para o celular*. **Nada é copiado**: a caixa do celular guarda só onde o arquivo está, e o celular baixa direto de lá. Tirar da caixa (✕) não apaga o arquivo. Arquivo que você apagar ou mover no PC sai da caixa sozinho.

Pelo celular dá para buscar, ver fotos e vídeos, baixar, favoritar, montar coleções, dar nomes às pessoas e enviar para o Premiere do PC. Apagar ou mover arquivos, gravar XMP, indexar e mudar configurações ficam só no computador.

Se o celular não abrir, o Firewall do Windows está bloqueando a porta 8766. Clique em **Permitir** no aviso do Windows, ou rode no PowerShell **como administrador**:

```
New-NetFirewallRule -DisplayName "BuscadorFAST (celular)" -Direction Inbound -Protocol TCP -LocalPort 8766 -Profile Private -Action Allow
```

Vídeos 4K em HEVC 10 bits (iPhone, a6700 em XAVC HS) podem não tocar no navegador do celular; as fotos e a maioria dos vídeos H.264 tocam normalmente.

## Linha de comando

```
BuscadorFAST.bat indexar "I:\Vídeos 2026" G:\      indexa pastas/discos e roda a IA
BuscadorFAST.bat atualizar                         percorre todos os discos marcados e depois faz o que falta
BuscadorFAST.bat pendentes                         faz tudo o que falta (palavras-chave, rostos, texto, fala)
BuscadorFAST.bat ia --refazer                      refaz as palavras-chave da IA (mantém as suas)
BuscadorFAST.bat rostos                            procura rostos nos arquivos pendentes
BuscadorFAST.bat texto                             lê o texto escrito dentro das fotos (OCR)
BuscadorFAST.bat transcrever                       transcreve a fala dos vídeos (precisa do disco conectado)
BuscadorFAST.bat duplicados                        procura arquivos idênticos (não apaga nada)
BuscadorFAST.bat discos                            lista os discos e o estado de cada um
```

## Instalar em outro computador

Mande para a pessoa o arquivo **BuscadorFAST-Instalador-x.y.z.exe** (fica na página de versões do repositório no GitHub ou na pasta `dist` depois de rodar `instalador\montar.bat`). Ela abre o arquivo, segue o assistente e, no fim, uma janela preta baixa o Python e a IA (alguns gigabytes). Com placa NVIDIA, a IA usa a placa; sem ela, usa o processador, bem mais devagar. Os detalhes estão no `README.md`.

Para gerar uma versão nova do instalador depois de mudar o programa: `instalador\montar.bat 1.0.1` (precisa do Inno Setup 6).

## Personalizar palavras-chave da IA

Edite `buscador/vocab.py` (uma linha por palavra: português + descrição em inglês) e rode `BuscadorFAST.bat ia --refazer`.

## Onde ficam os dados

Tudo em `data/`: `catalogo.db` (SQLite), `thumbs/` (miniaturas) e `faces/` (recortes de rosto).

### Backup

Botão **⚙** no topo. Com o programa aberto, o backup acontece **sozinho uma vez por dia** na pasta `BuscadorFAST-Backup` de outro disco do PC (dá para trocar o disco). São guardadas as últimas 7 cópias do catálogo (cerca de 13 MB cada) mais um espelho das miniaturas e rostos. Fotos e vídeos não são copiados. Se o backup falhar ou ficar mais de 3 dias sem rodar, aparece um ponto vermelho no ⚙.

Para voltar um backup, feche o programa (⏻) e rode:

```
BuscadorFAST.bat restaurar-backup "X:\BuscadorFAST-Backup\catalogo-AAAA-MM-DD_HHMM.zip"
```

O catálogo atual é guardado antes em `data\catalogo-antes-de-restaurar-<data>.db`.

## Formatos

Fotos: JPG, PNG, HEIC, TIFF, WebP, GIF, BMP e RAW (ARW, CR2, CR3, NEF, DNG, RAF, ORF, RW2…).
Vídeos: MP4, MOV, MKV, AVI, MTS, WMV, WebM, 3GP, MPG.
