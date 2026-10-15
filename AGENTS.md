# AGENTS.md

Resume Forge is a multi-user platform for ATS-friendly resumes: accounts with
email login, an HTTP API consumed by `resume-forge-front`, and the `cv` CLI
that builds LaTeX resumes from `data/cv.yaml`. Read
[README.md](README.md), `pyproject.toml`, `ruff.toml`, and the relevant source
and tests before changing code. The README roadmap lists the 10
implementation steps of the MVP.
Verify current behavior in the code; do not describe planned phases as
implemented.

## Workflow and tooling

- Use Python 3.14 and uv. Add dependencies with `uv add` or `uv add --dev`,
  updating both `pyproject.toml` and `uv.lock`; do not use `pip install`.
- Follow Ruff: four spaces, LF, 88 columns, single quotes, complete annotations,
  NumPy-style public docstrings (tests included), and absolute `app...` imports.
  Suppress with `# ruff: ignore[rule-name]`, never `noqa`, and keep it narrow.
- Use async APIs for I/O. Blocking work (files, subprocesses) runs in worker
  threads: `asyncio.to_thread` or `app.infra.process.run_command`.
- Use Loguru for application logs; terminal printing belongs to CLI output.
- `ruff` and `ty` are pinned with `==` in `pyproject.toml`, and
  `.pre-commit-config.yaml` uses the same versions in its `rev` fields. When
  upgrading one of them, change both files and run `uv lock`.
- Run `uv run pre-commit install` once per clone. The `ty` hook checks the
  whole project, `alembic/` included.
- Do not use em dashes (Unicode U+2014). The en dash is allowed only as the
  date-range separator of the resume.

## Architecture

```text
HTTP Resource -> Controller -> Service -> Repository -> YAML files / SQLModel
CLI command -> Service
```

| Layer | Responsibility |
| --- | --- |
| `app/resources/` | HTTP input/output DTOs |
| `app/controllers/` | Routes, resource mapping, error-to-status mapping |
| `app/services/` | Business rules: validation, rendering, ATS check |
| `app/repositories/` | Persistence: `data/` files today, PostgreSQL later |
| `app/models/` | `resume.py` (Pydantic schema of `cv.yaml`), table models later |
| `app/providers/` | Clients of external services: SMTP email, OpenRouter chat models |
| `app/cli_commands/` | Thin Typer adapters, registered in `app/infra/cli/command.py` |
| `app/infra/` | Settings, context, auth helpers, logging, database, processes, API composition |
| `templates/` | Jinja2 LaTeX templates and the plain-text template |

- Controllers call services, never repositories, and map service exceptions to
  statuses: 404 missing resume, 422 invalid resume or unknown template, 503
  missing external tool, 500 LaTeX failure.
- Services are module-level functions receiving `ctx: IContext`, independent
  of FastAPI and Typer. Only repositories read or write files in `data/` or the
  database. Build output in `build/` is written by `render_service`.
- Every route of a user declares `UserContext` (authenticated, scoped to the
  user by RLS). `RequestContext` has no user and is only for login routes.
  `FileContext` has no database session and serves the file-based resume
  routes; the CLI uses `get_file_context()`. Do not write
  `Depends(get_authenticated_context)` in a controller. The aliases set
  `scope='function'`, so FastAPI commits before it sends the response.
- Register routers in `app/infra/api/router.py`, all under `/api/v1`:
  `_AUTHENTICATED_API_ROUTERS` (router-level Bearer check, same scope as
  `UserContext`) or `_PUBLIC_API_ROUTERS` (login). Set `tags`. The OpenAPI `operationId` is
  `<TAG>-<function name>`; the front generates function names from it, so
  renaming a route function or a tag breaks the front. After changing routes,
  run `mani run openapi` from the workspace.
- Providers wrap one external service each, in `app/providers/<name>_provider.py`.
  They build the third-party client from settings, hold no business rules and
  do not access the database. Services call providers; repositories do not.
  The one exception is the email sender: `auth_controller` builds it with
  `get_email_sender` and passes it to `auth_service.request_login_code`, so
  tests pass a fake sender. Credentials are optional `SecretStr` settings, so
  the CLI and the tests run without them; the provider raises when a missing
  credential is needed (`get_chat` raises `ChatUnavailableError`).
- Settings are typed in `app/infra/settings.py`; update `.env.example` and the
  README table when adding one.
- Production may run several Uvicorn workers. Workers share no memory, and
  the `lifespan` runs once per worker. Do not keep state that must be global,
  such as caches, counters or rate limits, in module variables. Each worker
  has its own pool of `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections.

## Authentication and isolation

- Login is by a 6-digit code sent to the email, ported from Bolei. Any email
  receives a code, and the first verified code creates the account, so the
  API never reveals which emails exist. Codes are single-use, expire, and have
  bounded attempts, a resend cooldown and limits per email and per IP.
- Store only HMAC digests of codes (`AUTH_OTP_SECRET`) and SHA-256 digests of
  tokens. Refresh tokens are single-use; reuse revokes the whole session.
  Keep the row locks of challenge consumption and refresh rotation.
- API authentication is Bearer-only and reloads the user on every request.
  Never accept a user id from a request body, a query or an LLM output; the
  user comes from the context.
- Never log, trace or commit codes, tokens, digests or the email body.
  In development without `SMTP_HOST` (`Settings.uses_dev_login_code`), every
  code is `DEV_LOGIN_CODE` (`123456`) and the email goes to the log. Keep that
  rule tied to `APP_ENV=development`: in production a missing SMTP server
  must make the login unavailable, never accept a known code.
- Services that need a user call `require_user(ctx)` from `app/infra/auth.py`
  and raise `AuthorizationError` otherwise.
- Every user-owned table has `user_id` and a `user_isolation` policy created
  in its migration, comparing `user_id` with the transaction setting
  `nullif(current_setting('app.user_id', true), '')::bigint`, plus
  `ENABLE ROW LEVEL SECURITY`. `get_authenticated_context` sets
  `app.user_id`; repositories stamp `user_id` from the context on create.
  Identity tables (`app_user`, `auth_*`) have no policy: login reads them
  before a user is known.
- `DB_URL` uses a role without `SUPERUSER` or `BYPASSRLS` that does not own
  the tables (created by `infra/postgres/init/01-app-role.sh`); migrations use
  `DB_MIGRATION_URL`. The API logs a warning when `DB_URL` bypasses RLS.

## Resume rules

- `cv.yaml` is the single source of truth. `Resume` forbids unknown keys.
  Localized fields accept text or `{pt, en}`; `localize` falls back to the
  other language. Dates are `YYYY-MM` (`YYYY` allowed in education).
- `render_service.build_view` localizes the resume once; templates receive
  only the `ResumeView` as `cv` and never localize or format dates themselves.
- Section titles are the standard ones in `SECTION_TITLES`. Do not invent
  creative titles; ATS parsers look for these.
- Every template is one column and includes `_shared/preamble.tex.j2`, which
  keeps `fontenc` T1, `glyphtounicode` with `\pdfgentounicode=1`, `hyperref`
  metadata, and empty headers and footers. Never add icons, `fontawesome`,
  images, skill bars, or content in headers, footers or multi-column tables.
- LaTeX templates use `<< >>`, `((* *))` and `((# #))`. Every value is escaped
  by `escape_latex`; use the `url` filter for `\href` targets and `LatexRaw`
  only for LaTeX built in Python.
- The ATS check reads the PDF with `pdftotext -layout`. When adding a template,
  `cv build` for `pt` and `en` must pass it.
- Tailoring (phase 3) may only reorder, pick variants and swap synonyms of
  content that exists in `cv.yaml`; it never changes companies, titles, dates,
  numbers or adds technologies.

## Database

One model module and one repository module per table, following
`app/models/user.py` and `app/repositories/user_repository.py`. Table models
inherit `SQLBaseModel` (schema `resume_forge`), have a primary key and
`created_at`, `updated_at`, `deleted_at` as `timestamptz`, and follow the
`<Entity>Base / <Entity> / Create / Update / Filter` pattern with
`OptionalModel`. Repositories keep the standard operations (`read_<entity>`,
`count_<entities>`, paginated `read_<entities>`, `create`, `update`,
`delete` as soft delete); only repositories build queries. Register new model modules in `alembic/env.py` and add a
reviewed migration in `alembic/versions/`. `get_db_session()` owns
commit/rollback; never commit in services or repositories.

`diagrams/database.mmd` is the ER diagram of every table. Update it in the
same change as a table model and its migration.

## Commits

Commit or push only when the user asks. Work on a branch, never on `main` or
`develop` directly: `feat/<short-topic>`, `fix/<short-topic>`, `chore/<short-topic>`.

Message format, in English:

```text
<type>: <what changed, imperative, lowercase, no period>

<optional body: why, and what a reviewer cannot see in the diff>
```

- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `build`.
- Subject at most 72 characters. Body lines at most 72 characters, only
  when the subject is not enough; at most 5 short lines or bullets. Do not
  list every file or repeat the diff.
- No trailers or attribution: no `Co-Authored-By`, `Signed-off-by` or
  "Generated with" lines, and no links to AI tools or chat sessions, in
  commits, pull requests or versioned files.
- One logical change per commit. Split unrelated changes; do not mix a
  refactor with a feature.
- Commit only after `uv run lint` and `uv run test` pass.
- Never commit secrets, `.env` files, build output, caches or test reports.
- A schema change and its Alembic migration go in the same commit.
- Prefer a new commit to rewriting history. Amend or force-push only when
  the user asks, and only with `--force-with-lease` on a feature branch.

Examples:

```text
feat: add email code login
fix: keep the code step open after a wrong code
docs: describe the restricted database role
```

## Verification

Unit tests cover only `app/services/`, in `tests/unit/services/`, built with
`mock_context()`, `make_user()` and `make_resume()` from
`tests/unit/mocks/context.py`. Replace repositories and providers with mocks.
Replace `run_command` with a mock; tests must not need TeX Live, pdftotext, a
database or `.env`.

```bash
uv run lint
uv run test        # fails below 85% coverage of app/services
uv run cv build    # real compilation and ATS check, needs TeX Live
```

Report what changed, the validation performed, and remaining limitations.
