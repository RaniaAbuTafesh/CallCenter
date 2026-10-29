FROM python:3.12-slim

# git: to install Pipecat from its pinned commit.
# libglib2.0-0: small runtime library some OpenCV wheels expect.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so code changes don't reinstall everything.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Bot, knowledge base and web page.
COPY demo_bot.py raghad_organics_knowledge.txt ./
COPY raghad_ui ./raghad_ui

# Railway provides PORT; fall back to 7860 for local Docker runs.
EXPOSE 7860
CMD ["sh", "-c", "python demo_bot.py -t webrtc --host 0.0.0.0 --port ${PORT:-7860}"]
