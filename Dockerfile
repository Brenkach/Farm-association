FROM python:3.9-slim
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Залежності (версії зафіксовано в requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir --only-binary :all: --require-hashes -r requirements.txt
RUN pip uninstall -y setuptools wheel
# Копіюємо лише потрібні файли, а не весь контекст
COPY app.py extensions.py models.py routes.py ./
COPY templates/ templates/
COPY static/ static/

# Непривілейований користувач замість root
RUN useradd --create-home appuser
USER appuser

EXPOSE 5000
ENV FLASK_APP=app.py
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
