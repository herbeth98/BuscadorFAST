# O seletor "onde procurar" usa os mesmos nomes no computador e no celular

Written against: 684c172

## Evidence chain

- Surface: tela principal de busca, topo (`web/index.html`, `#searchForm`)
- Problem: o mesmo controle de modo de busca tem nomes diferentes conforme a largura da tela. No computador (largura acima de 800 px), o `<select id="mode">` mostra "Só palavras exatas", "Texto escrito na foto", "Falado nos vídeos" e "Sons nos vídeos". No celular (até 800 px), os botões `#modeChips` mostram "Palavras exatas", "Escrito na foto", "Falado" e "Sons".
- Design evidence:
  - `web/index.html:32-36`: as opções do select;
  - `web/index.html:55-59`: os botões `data-mode` com os nomes curtos;
  - `LEIAME.md:13`: o manual descreve *onde procurar* como "em tudo, palavras exatas, escrito na foto, falado, sons", ou seja, com os nomes curtos.
- Owner: `web/index.html`, nas opções de `#mode`.
- Scope and affected surfaces:
  - o seletor `#mode` do topo, visível acima de 800 px;
  - `web/style.css:247` e `:915`: largura do seletor (184 px, ou 150 px entre 1001 e 1280 px).
- Uncertainty: nenhuma sobre os nomes. Validar só que o texto mais longo cabe na largura de 150 px.

## Design decision

Usar no seletor do computador exatamente os nomes dos botões do celular, que são os nomes documentados no manual. Assim o modo escolhido tem um nome só em todo o app. Os valores (`value`) não mudam: `setMode()` em `web/app.js:162` e os botões `data-mode` continuam funcionando.

## Reuse

- Rótulos existentes em `web/index.html:55-59` (`#modeChips`)
- Exemplar: `web/index.html:55-59`

Nenhum componente novo.

## Changes

1. `web/index.html`, opções de `<select id="mode">` (linhas 32-36)
   - Change: trocar o texto das opções, sem mudar o `value`:
     - `texto`: "Só palavras exatas" → "Palavras exatas";
     - `escrito`: "Texto escrito na foto" → "Escrito na foto";
     - `falado`: "Falado nos vídeos" → "Falado";
     - `som`: "Sons nos vídeos" → "Sons";
     - `auto`: continua "Em tudo".
   - Preserve: os atributos `value`, `title` e `aria-label` do select e a ordem das opções.
   - Verify: abrindo o seletor no computador, as cinco opções têm os mesmos nomes dos botões do celular.

## Scope

- Inherit: o seletor `#mode` do topo.
- Verify: o placeholder do campo de busca, que `setMode` muda conforme o modo (`web/app.js:162-171`), continua coerente com os nomes. Os botões `#modeChips` não mudam.
- Exclude: o texto do botão "Buscar em tudo" no estado vazio (`web/app.js:108`), que é uma ação e não o nome de um modo, e qualquer mudança de comportamento.

## Validation

- Product: escolher cada modo no seletor do computador e conferir que a busca muda de modo como antes.
- Interface: conferir que o texto escolhido cabe sem corte nas larguras 1440, 1280, 1200 e 1024 px. O seletor mede 150 px entre 1001 e 1280 px; o maior texto é "Palavras exatas". Em 800 px ou menos, o seletor some e aparecem os botões.
- System: o app passa a ter uma única lista de nomes de modo, e nenhum rótulo novo é criado.
- Repository: `grep -n "Só palavras exatas\|Texto escrito na foto\|Falado nos vídeos\|Sons nos vídeos" web/index.html` → nenhum resultado.

## Stop conditions

- Pare se algum código ler o texto das opções em vez do `value`, procurando os rótulos antigos em `web/app.js`.
- Pare se o manual (`LEIAME.md`) tiver mudado para outros nomes.

## Design documentation

- After acceptance and validation: nenhuma. O `LEIAME.md:13` já usa esses nomes.
