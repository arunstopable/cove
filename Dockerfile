FROM python:3.11-slim

WORKDIR /app

COPY proxy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY shared/ ./shared/
COPY proxy/ ./proxy/

EXPOSE 8000

CMD ["uvicorn", "proxy.main:app", "--host", "0.0.0.0", "--port", "8000"]
