FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV CONTROL_HOST=0.0.0.0
ENV CONTROL_PORT=8080

WORKDIR /app

COPY hub/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY hub/control_hub /app/control_hub

EXPOSE 8080

CMD ["sh", "-c", "uvicorn control_hub.main:app --host ${CONTROL_HOST:-0.0.0.0} --port ${CONTROL_PORT:-8080}"]

