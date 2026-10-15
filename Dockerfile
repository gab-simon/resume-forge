ARG PYTHON_VERSION=3.14
ARG DISTRO=trixie
ARG FLAVOR=slim
ARG UV_VERSION=0.12.5

# TOOLS
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS tools

# BUILDER
FROM python:${PYTHON_VERSION}-${FLAVOR}-${DISTRO} AS builder
COPY --from=tools /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY pyproject.toml uv.lock README.md main.py alembic.ini /app/
COPY app /app/app
COPY alembic /app/alembic
COPY data /app/data
COPY templates /app/templates

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked


# STAGE 3: RUNTIME
FROM python:${PYTHON_VERSION}-${FLAVOR}-${DISTRO}

ENV TZ=America/Sao_Paulo \
    LANG=pt_BR.UTF-8 \
    LANGUAGE=pt_BR:pt \
    LC_ALL=pt_BR.UTF-8 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt update && \
    apt install -y --no-install-recommends tzdata locales \
        texlive-latex-base texlive-latex-recommended texlive-latex-extra \
        texlive-fonts-recommended lmodern poppler-utils && \
    sed -i -e 's/# pt_BR.UTF-8 UTF-8/pt_BR.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt clean && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 999 nonroot && \
    useradd --system --gid 999 --uid 999 --create-home nonroot

COPY --from=builder --chown=nonroot:nonroot /app /app
RUN mkdir -p /app/build && chown nonroot:nonroot /app/build

USER nonroot
WORKDIR /app
