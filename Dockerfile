# Use official Python runtime as a parent image
# Slim version for smaller size
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# Install system dependencies
# ffmpeg is required for faster-whisper and librosa
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Set environment variable for HuggingFace cache directory
ENV HF_HOME=/app/models/cache

# Create cache directory
RUN mkdir -p /app/models/cache

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the default Whisper model ('tiny') during build phase to avoid runtime 429 errors
RUN python -c "from faster_whisper import download_model; download_model('tiny')"

# Pre-download the Threat Classifier model (DistilBert) during build phase
RUN python -c "from transformers import DistilBertTokenizer, DistilBertForSequenceClassification; model_id='distilbert-base-uncased-finetuned-sst-2-english'; DistilBertTokenizer.from_pretrained(model_id); DistilBertForSequenceClassification.from_pretrained(model_id)"

# Copy application code
COPY . .

# Create a non-root user for security (Cloud Run best practice) and give ownership of the cache
RUN addgroup --system appgroup && adduser --system --group appuser && chown -R appuser:appgroup /app
USER appuser

# Disable HuggingFace Hub network calls at runtime
ENV HF_HUB_OFFLINE=1

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
