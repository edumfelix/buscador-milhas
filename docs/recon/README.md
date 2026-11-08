# Reconhecimento — busca award em FOR

Este diretório guarda apenas achados técnicos **sem cookies, tokens, CPF, e-mail ou número de programa**. As respostas reais usadas em testes devem ser sanitizadas em `tests/fixtures/`.

## Fontes

- LATAM: https://github.com/eduard0vieira/award-tool/blob/main/docs/recon/latam.md
- Azul: https://github.com/eduard0vieira/award-tool/blob/main/docs/recon/azul.md
- Smiles: https://github.com/eduard0vieira/award-tool/blob/main/docs/recon/smiles-blocking.md

## LATAM Pass — v2

- A busca com milhas é anônima? **Não.** `redemption=true` redireciona para `auth.latamairlines.com`.
- Login Auth0 com e-mail/CPF, senha e MFA (WhatsApp ou e-mail). Cada etapa é um POST com 302.
- Busca de dinheiro funciona sem login, com calendário de dois meses por chamada; a busca award é dia a dia e não tem versão anônima.
- Preço de ida e volta é calculado em par (`redemption-options`), não somando as pernas.
- Decisão do MVP: **não implementar**. A v2 pode avaliar importação manual de cookie de sessão, sem armazenar senha.

## Smiles (Gol)

- Busca de convidado funciona com a chave pública do site e `channel: WEB`.
- `calendarDayList` só vem com `WEB` e cobre ~7 dias por chamada (≈26 chamadas por rota/cabine para 180 dias).
- **406 JSON = quota por IP** (`referenceId` + `clientIP`). Trocar host, sessão ou cookies não ajuda; só o tempo repõe. O bloqueio observado durou ~87 min.
- Um IP novo suportou ~372 chamadas seguidas a ~7s; o orçamento conservador do projeto é ~180 chamadas/execução.
- 452 = fora da janela de venda (corte em hoje + 329 dias); não é bloqueio.
- 452 embrulhando 503 = afinidade de load balancer presa; limpar `akaalb_*`, replantar a sessão e tentar uma vez.
- Erros transitórios de `flightList` (~10% dos dias) passam no primeiro retry.
- Ida e volta custa ~2×; o MVP busca somente ida.

### API usada pelo adaptador

- `GET https://api-air-flightsearch-prd.smiles.com.br/v1/airlines/search`
  com `originAirportCode`, `destinationAirportCode`, `departureDate`,
  `adults`, `children=0`, `infants=0`, `forceCongener=false`.
- Headers: `x-api-key` (chave pública do app), `channel: WEB`,
  `accept: application/json`, `accept-language: pt-BR`.
- O fetch precisa sair de uma página **na origem da API**; por isso o
  adaptador usa Playwright: abre o site, depois a raiz da API (403/406 como
  documento é esperado) e chama o endpoint via `page.evaluate`.
- Resposta: `requestedFlightSegmentList[0].flightList` (voos do dia pedido,
  com `cabin`, `fareList`, `stops`, `legList`, `g3.costTax`) e
  `calendarDayList` (menor valor de ~6 dias ao redor, sem cabine/taxas).
- O adaptador pede o dia central da janela: a econômica usa o calendário
  inteiro; a executiva usa o detalhe do dia central (1/7 de amostragem).
- Fare escolhida: `SMILES_CLUB`, com fallback para `SMILES`; `SMILES_MONEY`
  e `MONEY` são ignoradas. Taxas de parceiros vêm `null`, não 0.
- O IP local de desenvolvimento recebeu **406** (quota), então o parser foi
  validado com fixture e o gate G0 deve ser rodado no runner.

## Azul Fidelidade

- Deep link validado no recon:
  `https://www.voeazul.com.br/br/pt/home/selecao-voo`
  com `c[0].ds`, `c[0].std` em `M/D/YYYY`, `c[1]` para volta e `cc=PTS` (pontos). Os colchetes vão crus.
- Token de sessão em `POST /authentication/api/authentication/v1/token`; headers `authorization`, `ocp-apim-subscription-key` (chave pública), `device: novosite`, `culture: pt-BR`.
- Disponibilidade em `POST .../reservation/availability/v6/availability` com `criteria[]`, `passengers[]`, `currencyCode: BRL`.
- `httpx` puro e `page.request` recebem 403; **só a requisição montada pela própria página passa**. Playwright com interceptação de rota, alterando apenas `postData`, retorna 200.
- Máximo de **6 datas por chamada**; 7+ retorna 400.
- **8 navegações em ~47s** dispararam 403 "unusual activity" por IP, com bloqueio >30 min. Pacing para evitar o bloqueio ainda não foi medido.
- `amountLevel` 1 = tudo em pontos; 2–5 adicionam dinheiro. `remainingSeats` é assento físico, não inventário award. Taxas = `taxesAndFees` + `convenienceFee`. A cabine doméstica pode vir nula.

## Gate G0

Antes de implementar os adaptadores, rodar o workflow manual `discovery` (ou `python -m buscador discover --providers all`) localmente e no runner do GitHub:

1. Se Smiles responder 406 de imediato ou Azul bloquear nas primeiras navegações a partir do IP do runner, **não construir o adaptador afetado**.
2. Fallback: Smiles-only + links ou mover a coleta para uma VM Oracle no Brasil, commitando os dados no mesmo repositório.
3. Proibido: resolver CAPTCHA, usar plugins stealth, proxies residenciais ou rotação de IP para burlar limites. Ao bloquear, parar e degradar.

O probe atual valida apenas a conectividade HTTP das páginas. O spike completo (M1) deve usar Playwright para interceptar as buscas award reais, medir o pacing e gerar fixtures sanitizadas.

## Deep links

| Programa | Estado |
|---|---|
| Smiles | `/mfe/emissao-passagem/` com `adults`, `cabin=ALL`, `departureDate` (epoch ms), `tripType=2`, `originAirport`, `destinationAirport` (validado) |
| Azul | Validado no recon (`c[0]`, `c[1]`, `cc=PTS`, M/D/YYYY) |
| LATAM | `oferta-voos` com `redemption=true`; abre login — v2 |
| Parceiros | Página de busca oficial; sem parâmetros inventados |
