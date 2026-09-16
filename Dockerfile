# 1. Базовий образ Python 3.9
FROM python:3.9-slim

# 2. Робоча директорія
WORKDIR /app

# 3. Встановлення залежностей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Копіювання коду проєкту
COPY . .

# 5. Відкриваємо внутрішній порт
EXPOSE 5000

# 6. Вказуємо точку входу для Flask
ENV FLASK_APP=app.py

# 7. Запуск Flask на порту 5000
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]