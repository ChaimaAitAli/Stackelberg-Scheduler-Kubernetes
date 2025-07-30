FROM python:3.10-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --timeout 1000 --retries 5 -r requirements.txt
CMD ["uvicorn", "stackelberg_sidecar:app", "--host", "0.0.0.0", "--port", "5000"]
