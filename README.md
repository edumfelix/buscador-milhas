# Buscador de Milhas — Fortaleza (FOR)

Buscador pessoal de passagens emitidas com milhas saindo de **Fortaleza (FOR)**, com página estática atualizada a cada **6 horas** e alertas no Telegram para oportunidades novas e quedas de preço.

O projeto é 100% Python, roda em GitHub Actions e publica a página no GitHub Pages. O estado fica em arquivos JSON versionados; não há servidor, banco gerenciado nem custo mensal.

## Status atual

- **M0 concluído:** configuração, modelos, estado, deduplicação, alertas, site, Telegram, CLI, testes e workflows.
- **M1 concluído:** probe HTTP e probe de API real (`discover --api`) para o gate G0; recon documentado.
- **M2 concluído:** adaptador **Smiles** real (Playwright + API interna, calendário de 7 dias, parser com fixture). O IP local deste ambiente está com quota 406, então a validação ao vivo precisa ser feita pelo workflow `discovery` a partir do runner do GitHub.
- **M3 pendente:** adaptador **Azul** (Playwright/interceptação, lotes de 6, pacing). Até lá, Azul aparece como "Em implementação".
- **LATAM Pass:** fora do MVP; exige login (Auth0 + MFA) e fica para a v2.
- **Modo demo:** gera dados determinísticos, sem rede, para validar todo o pipeline.

> O workflow agendado já funciona e publica a página com o status de cada provedor. Se o IP do runner estiver bloqueado, o Smiles degrada para o status "Bloqueado" sem apagar dados; o probe G0 mostra o motivo.

## Como funciona

```
GitHub Actions (cron 0 */6 * * *)
        │
        ├── Python: coleta Smiles + Azul com orçamento e rodízio
        ├── Atualiza data/state.json + data/history.jsonl
        ├── Gera site/index.html com Jinja2
        ├── Envia um digest ao Telegram
        └── Commita o estado e publica o site no GitHub Pages
```

- **Smiles:** adaptador implementado com busca de convidado, calendário de ~7 dias e quota por IP (HTTP 406). A econômica usa o calendário inteiro da janela; a executiva internacional usa o detalhe do dia central (o calendário não traz cabine), então é amostrada em 1 dia a cada 7. A chamada é compartilhada entre as cabines quando a janela coincide.
- **Azul:** busca de convidado via Playwright/interceptação, lotes de 6 datas, limite de ~8 navegações por IP. Planejado para nacional econômica.
- **Rodízio:** a página é regerada a cada 6h; cada rota avança no horizonte de 180 dias. Smiles completa o ciclo em ~1–2 dias; Azul em ~1 semana. Cada card mostra há quanto tempo foi verificado.
- **Links:** Qatar, Iberia, Copa, Flying Blue, Etihad e Aeromexico aparecem como busca manual (sem coleta automática). TAP fica desabilitada por padrão.

## Limitações conhecidas

- **LATAM exige login** para buscar com milhas; não armazenamos credenciais. Fica para a v2 (cookie de sessão ou outro mecanismo).
- **Ida e volta** não é precificada: a busca é somente ida e o site oferece links com retorno sugerido em +7/+14/+21 dias. Nunca somamos as pernas.
- **Disponibilidade muda rápido:** confirme sempre no site do programa antes de emitir.
- **Scraping é frágil:** endpoints e anti-bots mudam. Cada provedor é isolado; uma falha não apaga os dados anteriores.
- **Uso pessoal:** volume baixo, sem revenda e sem burlar CAPTCHA/proxy. Se um programa bloquear, ele degrada para link-only.

## Desenvolvimento local (Windows)

```bat
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -U pip
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m playwright install chromium
```

O Chromium é necessário para o Smiles real e para o probe de API; o modo demo não usa navegador.

O modo demo não usa rede:

```bat
.venv\Scripts\python -m buscador run --demo --data-dir .tmp\data --site-dir .tmp\site --max-units 20 --no-alerts
.venv\Scripts\python -m http.server 8000 --directory .tmp\site
```

Abra <http://localhost:8000>. O primeiro run é *bootstrap*: registra a linha de base e não envia alertas.

Comandos úteis:

```bat
.venv\Scripts\python -m buscador config validate
.venv\Scripts\python -m buscador run --providers smiles --dry-run --data-dir .tmp\data --site-dir .tmp\site
.venv\Scripts\python -m buscador site --data-dir .tmp\data --site-dir .tmp\site
.venv\Scripts\python -m buscador discover --providers all --out artifacts\discovery.json
.venv\Scripts\pytest -q
.venv\Scripts\ruff check .
```

O `discover` testa uma busca real por provedor por padrão (gate G0) e consome uma chamada do Smiles; use `--no-api` para checar apenas as páginas.

## Configuração

Tudo fica em `config.yaml`:

- `origin`, `horizon_days`, `adults`, `timezone`.
- `destinations.domestic` e `destinations.international`.
- `providers`: Smiles e Azul, com regiões, cabines, janela de datas, orçamento e atraso.
- `links`: programas somente-link (Qatar, Iberia, Copa, Flying Blue, Etihad, Aeromexico; TAP desabilitada).
- `coverage`: rotas "quentes", idade máxima do dado e limite de dados antigos.
- `alerting`: limiares de nova/queda, suspeita e limites do Telegram.
- `site`: título e número máximo de cards.
- `paths`: dados, templates, estáticos e saída do site.

## Telegram

1. Crie um bot com `@BotFather` e guarde o token.
2. Envie `/start` ao bot.
3. Descubra o `chat_id`:

   ```bat
   .venv\Scripts\python -m buscador telegram-chat-id --token "SEU_TOKEN"
   ```

4. Teste o envio:

   ```bat
   .venv\Scripts\python -m buscador alerts test --token "SEU_TOKEN" --chat-id "SEU_CHAT_ID"
   ```

5. No GitHub, cadastre os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

O bot é somente de saída (`sendMessage`), sem webhook ou polling em produção. O primeiro run é silencioso para evitar uma avalanche de mensagens.

## GitHub

1. Crie um repositório **público** (Pages grátis e Actions ilimitadas no plano Free).
2. Faça o push do projeto.
3. Em **Settings → Pages**, selecione **GitHub Actions** como fonte.
4. Em **Settings → Secrets and variables → Actions**, cadastre os dois secrets do Telegram.
5. Rode o workflow **discovery** (manual) e baixe o artifact para ver o gate G0 do IP do runner.
6. Rode o workflow **atualizar** com `providers=smiles,azul`. Se o Smiles estiver bloqueado, a página mostra o status e os dados antigos permanecem.
7. O cron `0 */6 * * *` roda às 21h, 03h, 09h e 15h de Fortaleza.

Observações:

- O workflow commita `data/state.json` e `data/history.jsonl` com `[skip ci]`; o `GITHUB_TOKEN` não dispara outro workflow.
- Não proteja `main` contra o push do bot (ou permita explicitamente o workflow).
- Se o repositório for privado, use Vercel/Cloudflare Pages para o site e considere o limite de 2.000 min/mês do Actions.
- O cron do GitHub pode atrasar alguns minutos; a página mostra a hora real da última atualização.

## Dados e reset

- `data/state.json`: oportunidades atuais, cobertura por data, status dos provedores e últimas execuções.
- `data/history.jsonl`: observações de preço, podadas para 180 dias.
- Para recomeçar, faça backup e apague os dois arquivos; o próximo run cria uma nova linha de base (sem alertas).
- O modo demo com `--data-dir .tmp\data` não toca no estado real.

## Estrutura

```
src/buscador/
  cli.py           # run, site, discover, alerts test, telegram-chat-id, config validate
  config.py        # config.yaml + validação
  models.py        # SearchQuery, Opportunity, ScanOutcome, Alert, ProviderRun
  state.py         # dedupe, cobertura, histórico, alertas, persistência JSON
  runner.py        # orquestra provedores, orçamento, deadline, rodízio
  render.py        # Jinja2 -> site/index.html
  deeplinks.py     # links de busca e ida/volta
  telegram.py      # Bot API
  discovery.py     # probe HTTP + API real (G0)
  providers/
    base.py        # interface, erros, pacing
    demo.py        # dados fake determinísticos
    smiles.py      # adaptador real (Playwright + API interna)
    azul.py        # adaptador pendente (M3)
templates/index.html.j2
static/style.css
static/app.js
data/state.json
data/history.jsonl
tests/
docs/recon/
```

## Testes e verificação

```bat
.venv\Scripts\ruff check .
.venv\Scripts\pytest -q
```

O CI roda lint + testes em push/PR. O workflow `discovery` é manual e sobe um relatório de conectividade como artefato (30 dias).

## Recon

Os achados que fundamentam o desenho estão em [`docs/recon/README.md`](docs/recon/README.md):

- LATAM exige login (Auth0 + MFA).
- Smiles tem quota por IP (406) e calendário de 7 dias.
- Azul exige Playwright/interceptação, 6 datas por chamada e bloqueio após ~8 navegações.

## Roadmap

- **M2 concluído:** adaptador Smiles (sessão, calendário, orçamento, parser, fixtures).
- **M3:** adaptador Azul (Playwright, lotes de 6, cursor de 60 dias, pacing).
- **M4:** polimento dos links internacionais e da página.
- **v2:** LATAM com sessão autenticada, TAP, mais destinos e, se necessário, API seats.aero.

## Aviso

Projeto pessoal, sem vínculo com companhias aéreas ou programas de fidelidade. Disponibilidade e valores mudam rápido; confirme no site do programa. O scraping é feito em modo convidado, com baixo volume, sem armazenar credenciais e sem burlar mecanismos de proteção.
