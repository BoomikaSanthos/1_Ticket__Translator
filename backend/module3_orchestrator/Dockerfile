# backend/module3_orchestrator/Dockerfile
FROM python:3.14-slim
RUN useradd -ms /bin/bash appuser
USER appuser
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 5003
CMD ["python", "module3_orchestrator.py"]