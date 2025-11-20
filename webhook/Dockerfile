# Containerización para Cloud Run
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["functions-framework", "--target=whatsapp_webhook", "--source=main.py", "--port=8080"]
