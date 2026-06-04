FROM python:3.12-slim
WORKDIR /app
COPY services/decode_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# core lib + service code (build context = repo root)
COPY core /app/core
COPY services/decode_service /app/services/decode_service
COPY services/__init__.py /app/services/__init__.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "services.decode_service.main"]
