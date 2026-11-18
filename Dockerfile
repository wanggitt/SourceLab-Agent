FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8765

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/research_agent_mvp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 10001 researcher && \
    mkdir -p /workspace/pdf /workspace/research_agent_mvp/data/uploads && \
    chown -R researcher:researcher /workspace/research_agent_mvp/data
USER researcher

EXPOSE 8765
CMD ["python", "app.py"]
