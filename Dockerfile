# syntax=docker/dockerfile:1.7
# ── Stage 1: build the web UI ──────────────────────────────────────────────────
FROM node:26-alpine AS ui-build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run build

# ── Stage 2: platform (API + UI + pipeline tooling) ───────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="vmware-migration-agent" \
      org.opencontainers.image.description="Turn vSphere discovery into validated, compliant Terraform and deploy it with human approval." \
      org.opencontainers.image.source="https://github.com/blacksoxx/vmware-migration-agent" \
      org.opencontainers.image.licenses="MIT"

# Populated by BuildKit for the build platform (amd64 on x86 hosts, arm64 on Apple Silicon).
ARG TARGETARCH
ARG TERRAFORM_VERSION=1.17.1
ARG TFLINT_VERSION=0.66.0
ARG OPA_VERSION=1.22.2
ARG DOCKER_CLI_VERSION=29.9.3

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Terraform: no update checks, no interactive prompts, provider cache in the user's home.
    CHECKPOINT_DISABLE=1 \
    TF_IN_AUTOMATION=1 \
    TF_INPUT=0 \
    TF_PLUGIN_CACHE_DIR=/home/appuser/.cache/vmware-migration-agent/terraform-plugins

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL -o /tmp/terraform.zip \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
    && unzip /tmp/terraform.zip -d /usr/local/bin \
    && rm -f /tmp/terraform.zip

RUN curl -fsSL -o /tmp/tflint.zip \
    "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${TARGETARCH}.zip" \
    && unzip /tmp/tflint.zip -d /usr/local/bin \
    && chmod +x /usr/local/bin/tflint \
    && rm -f /tmp/tflint.zip

RUN curl -fsSL -o /usr/local/bin/opa \
    "https://openpolicyagent.org/downloads/v${OPA_VERSION}/opa_linux_${TARGETARCH}_static" \
    && chmod +x /usr/local/bin/opa

# Docker CLI only (no daemon). mcp_client starts the Terraform MCP server with `docker run`,
# so at runtime either mount /var/run/docker.sock, set DOCKER_HOST, or run with --no-mcp /
# deterministic mode (the default), which never needs it.
RUN case "${TARGETARCH}" in \
        amd64) DOCKER_ARCH="x86_64" ;; \
        arm64) DOCKER_ARCH="aarch64" ;; \
        *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/docker.tgz \
        "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_CLI_VERSION}.tgz" \
    && tar -xzf /tmp/docker.tgz -C /tmp docker/docker \
    && install -m 0755 /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker /tmp/docker.tgz

RUN terraform version \
    && tflint --version \
    && opa version \
    && docker --version

WORKDIR /app

# Install dependencies first so source edits do not invalidate the layer.
COPY pyproject.toml AGENTS.md /app/
RUN pip install --upgrade pip && pip install .

COPY . /app
COPY --from=ui-build /ui/dist /app/ui/dist
RUN pip install --no-deps .

# Non-root runtime user; /app is read-only for it, writable state lives under /app/output
# and /home/appuser (mount volumes there; see docker-compose.yml).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/output/runs /home/appuser/.cache/vmware-migration-agent/terraform-plugins \
    && chown -R appuser:appuser /app/output /home/appuser

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

# Default: API + UI. For the CLI: docker compose run --rm agent python -m cli.main terragen ...
CMD ["python", "-m", "cli.main", "serve", "--host", "0.0.0.0", "--port", "8080"]
