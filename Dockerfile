FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install WhatsApp deps (optional, ignore failures)
RUN pip install --no-cache-dir httpx twilio 2>/dev/null || true

# Copy application code
COPY . .

# Pre-create storage dirs
RUN mkdir -p \
    storage/sessions \
    storage/memory \
    storage/workspace \
    storage/security \
    storage/soul \
    storage/plans \
    storage/bus \
    storage/research/benchmarks \
    storage/human_review \
    skills/custom

# Git identity
RUN git config --global user.email "agent@enterprise-claw.local" \
    && git config --global user.name "Enterprise Claw Agent"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
