FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 agent
WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install WhatsApp deps separately (optional)
RUN pip install --no-cache-dir httpx twilio 2>/dev/null || true

# Copy application code
COPY --chown=agent:agent . .

# Create storage directories
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
    skills/custom \
    && chown -R agent:agent storage skills

# Switch to non-root
USER agent

# Git identity for the git ratchet tool
RUN git config --global user.email "agent@enterprise-claw.local" \
    && git config --global user.name "Enterprise Claw Agent"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
