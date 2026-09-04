FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY c_invent ./c_invent
COPY config.yaml ./config.yaml
COPY api_server.py ./api_server.py
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
