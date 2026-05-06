FROM python:3.11-slim

# Install PyTorch CPU and other dependencies
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir matplotlib numpy

# Copy source code and scripts
WORKDIR /app
COPY src/ /app/src/
COPY scripts/ /app/scripts/
RUN chmod +x /app/scripts/*.sh

CMD ["bash"]
