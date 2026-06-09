# backend/module2_ticket_manager/Dockerfile
FROM python:3.14-slim
RUN useradd -ms /bin/bash appuser
USER appuser
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 5002
CMD ["python", "module2_ticket_manager.py"]