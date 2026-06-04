FROM python:3.12-slim
WORKDIR /app
COPY services/dump_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core /app/core
COPY services/dump_agent /app/services/dump_agent
COPY services/__init__.py /app/services/__init__.py
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "services.dump_agent.main"]
