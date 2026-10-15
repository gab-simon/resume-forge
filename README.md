# Resume Forge

Currículo como código: um único `data/cv.yaml` alimenta templates LaTeX de
coluna única, ATS-friendly, e um comando gera PDF, texto puro e o `.tex`.
A especificação completa está em `CV como Código CMS de Currículo LaTeX
ATS-Friendly.md`, na raiz do workspace.

- **Contas:** login por código de 6 dígitos enviado ao e-mail, sem senha. A
  conta é criada no primeiro login.
- **CLI `cv`:** valida o YAML, gera o currículo e roda a checagem ATS com
  `pdftotext`.
- **API:** as mesmas operações por HTTP, para o front
  ([resume-forge-front](https://github.com/gab-simon/resume-forge-front)).
- **Checagem ATS:** ordem das seções, acentos (T1), ligaduras
  (`glyphtounicode`) e contato no topo da página 1.

Python 3.14, uv, FastAPI, Typer, Jinja2, pdfLaTeX, PostgreSQL 18, SQLModel e
Alembic. A CLI gera o currículo sem banco; a API precisa dele para as contas.

## Desenvolvimento local

Instale Python 3.14, uv, TeX Live e poppler-utils:

```bash
sudo apt install texlive-latex-base texlive-latex-recommended \
  texlive-latex-extra texlive-fonts-recommended lmodern poppler-utils

uv sync --locked
cp .env.example .env
```

Pelo workspace, `mani run setup --all` faz o mesmo nos dois repositórios.

## Currículo

Edite `data/cv.yaml`. Texto simples vale para todos os idiomas; um mapa
`{pt: ..., en: ...}` traduz. Datas usam `YYYY-MM` (`end: null` é o emprego
atual) e `section_order` define quais seções aparecem e em que ordem.

```bash
uv run cv validate                     # valida o YAML
uv run cv schema                       # gera data/cv.schema.json (autocomplete no VS Code)
uv run cv templates                    # lista os modelos
uv run cv build -t classic -l pt       # gera build/classic/pt/cv.{pdf,txt,tex} e checa
uv run cv check build/classic/pt/cv.pdf --show-text
```

`cv build` termina com status 1 quando a checagem ATS falha. O `cv.txt` serve
para colar nos campos de experiência e habilidades da Gupy.

| Modelo | Status |
| --- | --- |
| `classic` | Pronto. Baseado no Jake's Resume |
| `compact`, `harvard`, `modern` | Fase 2 |

Um modelo novo é um diretório em `templates/` com `resume.tex.j2`, que inclui
`_shared/preamble.tex.j2`. Os templates usam `<< variável >>` e
`((* bloco *))` no lugar dos delimitadores do Jinja, e todo valor é escapado
para LaTeX.

## Banco e API

```bash
cp infra/postgres/.env.example infra/postgres/.env   # troque as senhas
docker compose --env-file infra/postgres/.env -f infra/postgres/compose.yaml up -d
uv run alembic upgrade head
uv run server
```

Na primeira subida, `infra/postgres/init/01-app-role.sh` cria o papel da
aplicação (`APP_DB_USER`). Ele não é dono das tabelas e não tem `BYPASSRLS`,
então o PostgreSQL aplica o isolamento por usuário. `DB_URL` usa esse papel;
`DB_MIGRATION_URL` usa o dono das tabelas (`POSTGRES_USER`). A API avisa no
log quando o papel de `DB_URL` ignora RLS. O script só roda com o diretório de
dados vazio; num banco já criado, crie o papel à mão com os mesmos comandos.

A API fica em `http://localhost:9000` e a documentação em
[`/docs`](http://localhost:9000/docs).

### Login

1. `POST /api/v1/auth/challenges` com `{"email": "...", "language": "pt-BR"}`
   envia um código de 6 dígitos e devolve `challenge_id`. A resposta é a
   mesma para e-mails com e sem conta.
2. `POST /api/v1/auth/challenges/{challenge_id}/verify` com o código,
   `device_id` (8 a 128 caracteres, fixo por navegador ou app) e `platform`
   (`web`, `android` ou `ios`) devolve `access_token`, `refresh_token`, o
   usuário e `is_new_user`. O primeiro código verificado de um e-mail cria a
   conta.
3. As demais rotas usam `Authorization: Bearer <access_token>`. O access
   token dura 60 minutos; `POST /api/v1/auth/refresh` troca o refresh token
   por um par novo. Reusar um refresh token já trocado revoga a sessão.

Com `EMAIL_BACKEND=console` o e-mail não é enviado: o código aparece no log
da API. Em produção use `EMAIL_BACKEND=smtp` com as variáveis `SMTP_*`.

| Rota | Uso |
| --- | --- |
| `POST /api/v1/auth/challenges`, `.../verify`, `/refresh`, `/logout` | Login, troca de token e logout |
| `GET /api/v1/auth/sessions`, `DELETE /api/v1/auth/sessions/{id}` | Sessões ativas da conta |
| `GET /api/v1/me`, `PATCH /api/v1/me` | Usuário, nome e preferências (idioma da interface, idioma do currículo, modelo padrão) |
| `GET /api/v1/resume`, `/templates`, `/pdf`, `/text`, `/check` | Currículo de `data/cv.yaml`, para qualquer conta logada (vira o currículo de cada conta na etapa 2) |
| `GET /health/v1/liveness`, `/health/v1/readiness` | Probes. Readiness responde 503 sem banco |

O front gera o client a partir do OpenAPI. `uv run cv openapi export -o
../resume-forge-front/openapi.json` exporta sem subir a API, e
`mani run openapi` exporta e regenera o client do front.

| Configuração | Uso |
| --- | --- |
| `CORS_ALLOWED_ORIGINS` | Origens do front, separadas por vírgula: `http://localhost:5173` |
| `LOG_LEVEL` | `TRACE`, `DEBUG`, `INFO`, `SUCCESS`, `WARNING`, `ERROR` ou `CRITICAL` |
| `DB_URL`, `DB_MIGRATION_URL` | PostgreSQL, sem o esquema da URI: papel da aplicação e dono das tabelas |
| `AUTH_OTP_SECRET` | Segredo de pelo menos 32 caracteres para o digest dos códigos. Sem ele, o login responde 503 |
| `AUTH_OTP_*`, `AUTH_ACCESS_TOKEN_TTL_MINUTES`, `AUTH_REFRESH_TOKEN_IDLE_TTL_DAYS`, `AUTH_SESSION_ABSOLUTE_TTL_DAYS` | Validade do código (10 min), tentativas (5), limites por e-mail e IP, validade dos tokens |
| `EMAIL_BACKEND`, `EMAIL_FROM`, `SMTP_*` | Envio do código: `smtp` ou `console` (desenvolvimento) |
| `RESUME_DATA_DIR`, `RESUME_TEMPLATES_DIR`, `RESUME_OUTPUT_DIR` | Diretórios de dados, modelos e saída. Padrão: `data/`, `templates/`, `build/` |
| `LATEX_COMMAND`, `PDFTOTEXT_COMMAND` | Executáveis externos. Padrão: `pdflatex`, `pdftotext` |

## Docker

A imagem inclui TeX Live e poppler-utils, então o PDF é o mesmo na máquina e
no CI.

```bash
docker compose up -d --build             # desenvolvimento, com reload
docker compose -f compose.prod.yaml up -d --build
```

O Compose monta `data/` e `build/`. O `compose.prod.yaml` aplica as migrações
no serviço `migrate` antes de subir a API.

## Qualidade

```bash
uv run lint     # ruff check, ruff format --check e ty check
uv run test     # testes de app/services com cobertura mínima de 85%
```

O workflow `code-quality` roda os dois e gera o currículo com todos os
modelos e idiomas, falhando se a checagem ATS falhar. Os PDFs ficam como
artifacts.

## Roadmap

O MVP está dividido em 10 etapas.

- [x] 0. Base: schema `Resume`, modelo `classic`, `cv build`, `cv check`, CI
- [x] 1. Usuários e login por código no e-mail
- [ ] 2. Currículo base por conta, com revisões e RLS
- [ ] 3 a 10. Prévia e modelos, versões, DOCX, ATS, IA, adaptação, tradução
