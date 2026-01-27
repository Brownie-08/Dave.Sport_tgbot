# Use Python slim image
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# Force reinstall dependencies
RUN pip install --no-cache-dir --upgrade -r requirements.txt

CMD ["python", "main.py"]
