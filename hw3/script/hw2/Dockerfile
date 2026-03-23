FROM ubuntu:24.04

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# System packages: Python + build tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Set workdir inside container
WORKDIR /workspace

# Copy repo into the image
COPY . /workspace

# Install Python deps
# hw1/req.txt exists; hw2 needs sklearn on top
# hw1/req.txt exists; hw2 needs sklearn on top
# Create a virtualenv and install Python deps there
RUN python3 -m venv /venv
ENV PATH="/venv/bin:${PATH}"

# Install Python deps into the venv
RUN pip install -r hw2/req.txt && \
    pip install scikit-learn

# Default shell (we'll override CMD when running if needed)
CMD ["/bin/bash"]
