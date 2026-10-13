FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY configs ./configs
COPY evaluations ./evaluations
COPY scripts ./scripts
ENV PYTHONPATH=/app/backend RAG_ROOT=/app RAG_HOME=/runtime HF_HOME=/runtime/model-cache DO_NOT_TRACK=1 MLFLOW_DISABLE_AGENT_HINT=1
CMD ["uvicorn","rag.main:app","--host","0.0.0.0","--port","8300"]
