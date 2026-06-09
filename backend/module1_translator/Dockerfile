# backend/module1_translator/Dockerfile
FROM python:3.14-slim

# Create a non‑root user (optional but recommended)
RUN useradd -ms /bin/bash appuser
USER appuser
WORKDIR /app

# Copy the whole backend folder (includes requirements.txt)
COPY . .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the service will listen on (5001)
EXPOSE 5001

# Run the Flask app
CMD ["python", "module1_translator.py"]