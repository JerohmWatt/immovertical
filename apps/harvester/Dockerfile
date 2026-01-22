FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install dependencies
COPY apps/harvester/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Set Python path to include /app for common module access
ENV PYTHONPATH=/app

# Application code will be mounted via volume in dev
# For production, we would COPY . .

CMD ["python", "src/main.py"]
