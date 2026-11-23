FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 UV_PYTHON_DOWNLOADS=0 PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# CI passes the ISO week, which reruns the next step once a week, so the image takes Debian's security fixes without waiting for a new base image.
ARG APT_REFRESH=""
# The app runs from .venv, which has no pip. The base image's pip carries its own urllib3, msgpack and setuptools, and scanners report them.
RUN echo "packages refreshed: ${APT_REFRESH}" && apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
    && /usr/local/bin/python -m pip uninstall --yes --root-user-action=ignore pip

# uv is mounted for this step only, so it is not in the final image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked

COPY nih_grant_matcher ./nih_grant_matcher
COPY streamlit_app.py .

RUN useradd --create-home --uid 1000 app && mkdir -p data outputs digests && chown -R app:app data outputs digests
USER 1000

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=3)"]

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
