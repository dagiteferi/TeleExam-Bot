FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create a non-root user
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

COPY --chown=user . .

# Expose port 7860 which is required by Hugging Face Spaces
EXPOSE 7860

# Run the webhook server (Hugging Face needs a port to be bound)
CMD ["python", "run.py"]
