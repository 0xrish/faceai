# Use Python 3.12 (compatible with torch==2.2.2 + easyocr)
FROM apify/actor-python:3.12

USER root

# Install system dependencies required for pdf2image (poppler)
RUN apt-get update \
 && apt-get install -y poppler-utils \
 && rm -rf /var/lib/apt/lists/*

# Switch back to non-root user (Apify best practice)
USER myuser

# Copy only requirements first (for better caching)
COPY --chown=myuser:myuser requirements.txt ./

# Install dependencies and print debug info
RUN echo "Python version:" \
 && python --version \
 && echo "Pip version:" \
 && pip --version \
 && echo "Installing dependencies:" \
 && pip install --no-cache-dir -r requirements.txt \
 && echo "All installed Python packages:" \
 && pip freeze

# Copy rest of the source code
COPY --chown=myuser:myuser . ./

# Compile Python files (sanity check)
RUN python -m compileall -q src/

# Run the actor
CMD ["python", "-m", "src"]