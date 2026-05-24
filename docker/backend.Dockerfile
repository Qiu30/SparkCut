FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG INSTALL_LOCAL_WHISPER=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/backend/.venv/bin:${PATH}" \
    VIDEO_CUT_DB_URL="sqlite:////app/data/videocut.db" \
    VIDEO_CUT_STORAGE_DIR="/app/storage" \
    VIDEO_CUT_PIPELINE_MODE="auto" \
    VIDEO_CUT_LLM_MODEL="GLM-5.1" \
    VIDEO_CUT_WHISPER_COMMAND='python scripts/run_whisper_base.py "{input}" --job-id {job_id} --material-id {material_id} --fingerprint {fingerprint} --model {model} --seconds {seconds} --language {language} --model-cache /app/model-cache/whisper --output-file "{output_file}"'

RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.aliyun.com/debian|g; s|http://security.debian.org/debian-security|https://mirrors.aliyun.com/debian-security|g' /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources 2>/dev/null || true \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

RUN python -m venv .venv \
    && .venv/bin/python -m pip install --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com \
    && .venv/bin/pip install \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        --timeout 60 \
        --retries 5 \
        fastapi==0.115.6 \
        uvicorn==0.34.0 \
        sqlalchemy==2.0.36 \
        python-multipart==0.0.20 \
        pydantic==2.10.4 \
    && if [ "$INSTALL_LOCAL_WHISPER" = "true" ]; then \
        .venv/bin/pip install --timeout 120 --retries 3 --index-url https://download.pytorch.org/whl/cpu torch \
        && .venv/bin/pip install \
            -i https://mirrors.aliyun.com/pypi/simple/ \
            --trusted-host mirrors.aliyun.com \
            --timeout 120 \
            --retries 3 \
            openai-whisper==20250625; \
    else \
        echo "Skipping local Whisper install; set VIDEO_CUT_BUILD_WITH_WHISPER=true to build it into the image."; \
    fi

COPY backend/app ./app
COPY backend/scripts ./scripts

RUN mkdir -p /app/data /app/storage /app/model-cache/whisper

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
