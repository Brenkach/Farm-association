# Контейнерна версія Farm API (ЛР-8): HTTP-сервер + той самий Lambda-обробник.
# Код обробника береться з serverless/lambda через додатковий контекст збірки "lambda"
# (у docker-compose.yml: additional_contexts), тому він не дублюється.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=lambda handler.py .
COPY app/server.py .

RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --start-period=15s --retries=2 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["python", "server.py"]
