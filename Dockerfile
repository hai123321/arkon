FROM python:3.12-slim

WORKDIR /app

# Cài đặt các system dependencies cần thiết (để xử lý ảnh, PDF nếu cần)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Python packages
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy toàn bộ mã nguồn
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command (sẽ được ghi đè trong docker-compose cho API và Worker)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5055"]
