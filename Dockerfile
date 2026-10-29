FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ ./server/
COPY frontend/ ./frontend/
RUN mkdir -p /app/data && useradd --uid 10001 --create-home godmode && chown godmode:godmode /app/data
USER godmode
EXPOSE 8383
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8383"]
