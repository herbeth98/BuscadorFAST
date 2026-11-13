# A aba escolhida dos controles segmentados usa a cor de ação

Written against: 684c172

## Evidence chain

- Surface: tela principal de busca, barra de resultados (`web/index.html`, `.sortbox` > `#kindSeg`: Tudo, Fotos, Vídeos, Prints)
- Problem: a aba escolhida do tipo aparece em branco (tema claro) ou cinza (tema escuro), sem a cor de ação. Na mesma barra, os botões Linha do tempo e Mapa, quando ligados, usam o tom de azul suave com texto azul.
- Design evidence:
  - `web/style.css:1-9`, cabeçalho de decisões: "uma cor de ação só (azul) para tudo o que é clicável ou escolhido";
  - `web/style.css:202`: `.seg button.on { background: var(--seg-on); font-weight: 600; }`, com `--seg-on` valendo `#ffffff` no claro (`:28`) e `#636366` no escuro (`:101`), que são cores neutras;
  - `web/style.css:421`: `.sortbox > button.on { background: var(--accent-soft); color: var(--accent); }`, o estado "escolhido" dos botões vizinhos;
  - `web/style.css:312`: `.vol.on` usa o mesmo par `--accent-soft` e `--accent` na lateral.
- Owner: `web/style.css`, regra `.seg button.on`, que é compartilhada por todos os controles segmentados.
- Scope and affected surfaces: todos os elementos `.seg`:
  - `#kindSeg`, na barra de resultados;
  - `#sidePeopleMode`, na lateral, quando há duas ou mais pessoas escolhidas;
  - `#combineMode`, na janela Pessoas;
  - `#dupesKind`, na janela Duplicados.
- Uncertainty: nenhuma sobre a cor. Validar o contraste do texto azul sobre o trilho cinza (`--track`) nos dois temas.

## Design decision

Mudar a regra compartilhada `.seg button.on` para o estado "escolhido" que já existe na mesma barra: fundo `--accent-soft` e texto `--accent`. Isso cumpre a decisão documentada da cor de ação e corrige todos os controles segmentados de uma vez, sem criar uma variante nova. O negrito (`font-weight: 600`) continua, para manter a leitura do item escolhido.

## Reuse

- Tokens: `--accent-soft` e `--accent` (definidos em `:root` e no bloco `prefers-color-scheme: dark` de `web/style.css`)
- Exemplar: `web/style.css:421` (`.sortbox > button.on`)

Nenhum componente novo.

## Changes

1. `web/style.css`, regra `.seg button.on` (linha 202)
   - Change: trocar `background: var(--seg-on)` por `background: var(--accent-soft); color: var(--accent);`. Manter `font-weight: 600`.
   - Preserve:
     - o trilho do controle (`.seg { background: var(--track) }`);
     - o hover dos itens não escolhidos (`.seg button:hover:not(.on)`);
     - a largura fixa de `.sortbox .seg`;
     - a animação `pop` do bloco "Movimento" no fim do arquivo.
   - Verify: em "Tudo, Fotos, Vídeos, Prints", o item escolhido fica com fundo azul suave e texto azul, igual ao botão Mapa ligado.
2. `web/style.css`, token `--seg-on` (linhas 28 e 101)
   - Change: remover as duas declarações de `--seg-on`, se nenhuma outra regra a usar depois da mudança 1.
   - Preserve: os demais tokens.
   - Verify: `grep -n "seg-on" web/style.css` → nenhum resultado.

## Scope

- Inherit: `#kindSeg`, `#sidePeopleMode`, `#combineMode` e `#dupesKind`.
- Verify:
  - a janela Pessoas: barra "Combinar pessoas", que já tem fundo `color-mix(...)` azulado, `web/style.css`, `.combine.active`. Confira se o item escolhido continua visível sobre esse fundo;
  - os botões da lateral `#sidePeopleMode` no celular, dentro da folha de filtros.
- Exclude: `.speech .seg`, as linhas da transcrição no visualizador. Elas usam a classe `seg` mas não têm `button.on`, então não são afetadas. Também fica de fora qualquer mudança de comportamento.

## Validation

- Product: trocar o tipo (Tudo, Fotos, Vídeos, Prints) e ver o resultado filtrar como antes.
- Interface:
  - telas: tema claro e escuro, em 1440×900 e em 375×812;
  - estados: Pessoas com duas pessoas marcadas (Juntas, Qualquer uma, Só elas) e Duplicados (Tudo, Fotos, Vídeos);
  - contraste: confira se o texto azul fica legível sobre `--accent-soft` em cima de `--track`.
- System: o estado "escolhido" passa a ter só duas formas, ambas com a cor de ação: preenchido (`--action`, nas pílulas de data e palavras-chave) e suave (`--accent-soft`, na lateral, nos botões da barra e agora nos segmentados). Nenhum token novo.
- Repository: `grep -n "\.seg button\.on" web/style.css` → as regras usam `--accent-soft` e `--accent`, e nenhuma usa `--seg-on`.

## Stop conditions

- Pare se o contraste do texto azul sobre o fundo suave ficar ilegível em algum tema; nesse caso, devolva para decisão de design em vez de inventar outro valor.
- Pare se aparecer outro uso de `--seg-on` fora de `.seg button.on`.

## Design documentation

- After acceptance and validation: no cabeçalho de `web/style.css`, acrescentar "escolhido: fundo `--accent-soft` + texto `--accent`; preenchido `--action` só nas pílulas de filtro".
