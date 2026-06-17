FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose proxy port
EXPOSE 8000

# Default command to run the proxy
CMD ["uvicorn", "proxy:app", "--host", "0.0.0.0", "--port", "8000"]
