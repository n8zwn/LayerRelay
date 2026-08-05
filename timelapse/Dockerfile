FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user. Creating /frames and /timelapses owned by this user
# means a fresh named volume for /frames inherits the right ownership, so the
# app can write without running as root.
RUN useradd -u 10001 -m -d /home/appuser -s /usr/sbin/nologin appuser \
    && mkdir -p /frames /timelapses /app \
    && chown -R appuser:appuser /frames /timelapses /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /app
COPY --chown=appuser:appuser timelapse.py /app/timelapse.py

USER appuser
EXPOSE 8088
# Shell form with 'exec' so python is PID 1 (gets SIGTERM to render on stop) and
# there are no quotes to get mangled by copy-paste.
CMD exec python -u timelapse.py
