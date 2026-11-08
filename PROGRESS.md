# Progresso — Buscador de Milhas (FOR)

Atualizado em **08/11/2026** (America/Fortaleza).

Este arquivo é o ponto de retomada do projeto: o que está pronto, o que está bloqueado, as decisões já tomadas e o próximo caminho. O passo a passo operacional fica no [README.md](README.md).

## Resumo

- **Página no ar:** https://edumfelix.github.io/buscador-milhas/
- **Repositório:** https://github.com/edumfelix/buscador-milhas
- **Branch padrão:** `master`
- **Pages:** fonte **GitHub Actions**; environment `github-pages` permite `master`.
- **Última publicação:** 08/11/2026 13:38 (America/Fortaleza).
- **CI:** verde no commit `e8d2731` (run 42500660305).
- **Dados atuais:** `bootstrap_done=true`, **0 oportunidades**.
  - Smiles: `blocked` — HTTP 406 (quota por IP) no runner do GitHub.
  - Azul: `not_implemented` — M3 pendente.
- **Telegram:** secrets cadastrados. Primeiro run é bootstrap silencioso; ainda não há alertas porque ainda não há oportunidades.

## O que já funciona

- Página estática responsiva, com filtros, status por provedor, links internacionais e deep links.
- Pipeline completo no GitHub Actions: coleta → estado → render → commit → Pages.
- Adaptador real do **Smiles** (`src/buscador/providers/smiles.py`):
  - Playwright abre o site e a origem da API;
  - endpoint interno `/v1/airlines/search`;
  - calendário de ~7 dias para econômica;
  - detalhe do dia central para econômica/executiva;
  - parser com fixture real;
  - taxas, voos, paradas, cabine e deep link de busca do Smiles.
- Estado JSON/JSONL com deduplicação, cobertura por data, histórico de preço, alertas de nova/queda e bootstrap silencioso.
- Telegram com digest, escape de HTML, limite de mensagens, cooldown e retry.
- `discover` com probe HTTP e **probe de API real** (gate G0).
- 41 testes + `ruff` limpos localmente.
- Modo demo sem rede para preview da página.
- Links somente-leitura para Qatar, Iberia, Copa, Flying Blue, Etihad e Aeromexico.
- Documentação de recon em `docs/recon/README.md`.

## O que está bloqueado ou pendente

| Item | Estado | Observação |
|---|---|---|
| Smiles em produção | Bloqueado | 406 por IP no runner; o adaptador está implementado |
| Azul Fidelidade | Pendente (M3) | Playwright + interceptação; 6 datas/chamada; ~8 navegações/IP |
| LATAM Pass | v2 | Exige login Auth0 + MFA; não armazenar senha |
| British Airways | Fora do MVP | Sem voo direto de FOR e sem parceria Smiles/Azul |
| TAP Miles&Go | Desabilitada | Atende ao critério (FOR–LIS), mas não estava na lista original |
| Executiva internacional | Amostrada | O calendário do Smiles não traz cabine; executiva usa o dia central (1/7) |
| Ida e volta | Somente link | A busca é de ida; a página sugere +7/+14/+21 dias |
| Oportunidades reais | Bloqueadas | Dependem de um IP com quota no Smiles |

## Decisões já tomadas

- Origem fixa **FOR**; horizonte de **180 dias**; 1 adulto.
- **Nacional: econômica. Internacional: econômica + executiva.**
- Scraping híbrido: Smiles implementado; Azul no M3; LATAM na v2.
- **Não armazenar credenciais** de companhias; somente busca de convidado.
- **Não burlar CAPTCHA/proxy/stealth**; ao bloquear, degradar e respeitar o IP.
- Fonte de dados: Smiles e Azul; links para os demais programas filtrados.
- Persistência em **JSON/JSONL no repositório**, sem SQLite no MVP.
- Hospedagem **GitHub Actions + Pages**, repositório público; custo R$ 0.
- Alertas: novas oportunidades + quedas ≥10% e ≥1.000 milhas; bootstrap silencioso.
- Cobertura em rodízio: página regerada a cada 6h; Smiles ~1–2 dias; Azul ~1 semana.
- Branch padrão `master`; CI configurado para `main` e `master`.

## Segurança

- Nunca versionar tokens, cookies ou credenciais. Use **GitHub Secrets**.
- Se o token do Telegram foi exposto em chat/log, **revogue no @BotFather** e atualize `TELEGRAM_BOT_TOKEN`.
- O repositório é público: os dados de disponibilidade são públicos, mas não coloque dados pessoais.
- O `.gitignore` cobre `.venv`, `.tmp`, `site`, `artifacts`, caches, relatórios do Playwright, backups de estado e logs.
- O token do Smiles no código é uma **chave pública de app**, não uma credencial de conta.

## Como retomar

### 1. Sincronizar e validar

```powershell
cd C:\Users\Admin\src\buscador-milhas
git pull --rebase origin master

.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m playwright install chromium

.venv\Scripts\ruff check .
.venv\Scripts\pytest -q
```

### 2. Ver o site e o estado atual

- Página: https://edumfelix.github.io/buscador-milhas/
- Actions: https://github.com/edumfelix/buscador-milhas/actions
- Estado: `data/state.json` e `data/history.jsonl`.
- O workflow `atualizar` roda a cada 6h; enquanto o IP estiver bloqueado, ele só atualiza o status e republica a página. Se quiser evitar chamadas inúteis, desabilite o cron temporariamente e rode manualmente depois de resolver o IP.

### 3. Preview local sem rede

```powershell
.venv\Scripts\python.exe -m buscador run --demo `
  --data-dir .tmp\data --site-dir .tmp\site --max-units 20 --no-alerts

.venv\Scripts\python.exe -m http.server 8000 --directory .tmp\site
```

### 4. Rodar o discovery

Pela UI: **Actions → discovery → Run workflow** e baixe o artifact. Localmente:

```powershell
.venv\Scripts\python.exe -m buscador discover `
  --providers all --out artifacts\discovery.json
```

O `discover` testa a API por padrão e consome uma chamada do Smiles. Use `--no-api` para checar apenas as páginas.

## Próximo passo recomendado: IP estável

O bloqueio do Smiles é **por IP**. O runner do GitHub usa IPs compartilhados e recebeu 406; o IP local também. A solução gratuita mais estável é uma **VM Oracle Cloud Always Free no Brasil**.

### Arquitetura proposta

1. VM Oracle Always Free (ARM) em **São Paulo**, Ubuntu 24.04.
2. Instalar Python 3.12+, Git, Playwright e Chromium.
3. Clonar o repositório; criar venv; instalar o projeto.
4. A VM roda a coleta a cada 6h:
   ```bash
   git pull --rebase
   python -m buscador run --providers smiles,azul --render
   git add data/
   git commit -m "chore: coleta VM [skip ci]"
   git push
   ```
5. O GitHub Pages continua publicando o site.

**Questão de arquitetura a resolver:** o workflow `atualizar` atual também coleta no runner. Se ele continuar rodando, pode sobrescrever o status `ok` da VM com `blocked`. A recomendação é criar um workflow **somente de publicação** (render + deploy, sem coleta), disparado depois do push da VM ou por cron, e deixar a coleta exclusivamente na VM. Alternativa: adicionar um modo `--no-collect` ao `atualizar`.

### Alternativas

| Opção | Custo | Prós | Contras |
|---|---|---|---|
| Oracle VM Always Free | R$ 0 | IP estável, controle total, roda Azul também | Cadastro/capacidade, manutenção, risco de instância ociosa |
| Esperar/retentar no GitHub | R$ 0 | Simples | IP compartilhado; bloqueio pode voltar |
| seats.aero API | ~US$ 9,99/mês | Dados confiáveis, cobre Smiles/Azul | Pago; não cobre LATAM |
| Página só de links | R$ 0 | Estável | Sem oportunidades automáticas |

## Depois do IP estável

### M3 — Azul Fidelidade

- Playwright com interceptação da requisição que a própria página monta (httpx puro recebe 403).
- Lotes de **6 datas** por chamada; 7+ retorna 400.
- ~8 navegações seguidas bloqueiam o IP; usar 8–10 navegações/execução e pacing (~20s).
- Cursor de 60 dias por rota; somente nacional econômica no MVP.
- `amountLevel=1` é tudo em pontos; taxas = `taxesAndFees` + `convenienceFee`; `remainingSeats` é assento físico, não award.
- Testar parser com a fixture `azul-real-multidata.json`.

### v2 — LATAM Pass

- Login Auth0 + MFA; busca award anônima redireciona para login.
- Avaliar importação manual de cookie de sessão, **sem armazenar senha**.
- Busca dia a dia; preço de ida+volta em par (`redemption-options`), nunca somando pernas.

### Outros

- TAP Miles&Go (FOR–LIS) e mais destinos.
- Avaliar seats.aero se o custo de manutenção do scraping crescer.
- Ajustar a amostragem de executiva (hoje 1/7) se necessário.

## Riscos e limites conhecidos

- **Smiles 406:** quota por IP; não insistir. O bloqueio pode durar ~87 min e voltar.
- **Azul 403/8 navegações:** limitar navegações e pacing; se não estabilizar, degradar para link-only.
- **Parsers mudam:** cada provedor é isolado; falha vira status degradado, sem apagar dados.
- **Dados em rodízio:** a idade aparece em cada card; a página é regerada a cada 6h.
- **Sem preço RT:** a ida e volta é apenas um link com sugestão de retorno.
- **Uso pessoal:** baixo volume, sem revenda, sem bypass.
- **Bootstrap:** a primeira varredura de cada rota não gera alertas; alertas começam na comparação seguinte.
- **Token do Telegram:** se exposto, revogar e atualizar o secret.

## Arquivos-chave

| Arquivo | Papel |
|---|---|
| `config.yaml` | origem, destinos, provedores, orçamentos, links e alertas |
| `src/buscador/providers/smiles.py` | adaptador real do Smiles |
| `src/buscador/providers/azul.py` | esqueleto do Azul (M3) |
| `src/buscador/runner.py` | orçamento, rodízio, deadline e status |
| `src/buscador/state.py` | dedupe, cobertura, histórico, alertas |
| `src/buscador/render.py` | geração da página |
| `src/buscador/telegram.py` | digest e envio |
| `src/buscador/discovery.py` | probe HTTP + API (G0) |
| `.github/workflows/atualizar.yml` | cron 6h + deploy Pages |
| `.github/workflows/discovery.yml` | probe manual G0 |
| `.github/workflows/ci.yml` | lint + testes em `main`/`master` |
| `docs/recon/README.md` | achados de recon |
| `tests/fixtures/` | fixtures sanitizadas |

## Checklist de retomada

- [ ] `git pull --rebase origin master`
- [ ] `ruff check .` e `pytest -q`
- [ ] Conferir a página e o status em Actions
- [ ] Rodar `discovery` e ver o G0 do IP atual
- [ ] Decidir entre Oracle VM, esperar ou link-only
- [ ] Se Oracle: criar VM, deploy key, cron e workflow de publicação
- [ ] Implementar Azul M3
- [ ] Avaliar LATAM v2
- [ ] Atualizar este arquivo ao final de cada etapa

## Referências

- Página: https://edumfelix.github.io/buscador-milhas/
- Repositório: https://github.com/edumfelix/buscador-milhas
- Actions: https://github.com/edumfelix/buscador-milhas/actions
- Recon externo: https://github.com/eduard0vieira/award-tool/tree/main/docs/recon
- GitHub Pages: https://docs.github.com/pages
- Telegram Bot API: https://core.telegram.org/bots/api
