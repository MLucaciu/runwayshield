FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# NodeSource drags in a system Python 3.13 at /bin/python3.
# Force /usr/local/bin (the image's 3.12) to always win so that
# `python3`, `python`, and `pip` resolve to the right interpreter.
RUN ln -sf /usr/local/bin/python3 /usr/bin/python3 && \
    ln -sf /usr/local/bin/python3 /usr/bin/python  && \
    ln -sf /usr/local/bin/pip3    /usr/bin/pip3     && \
    ln -sf /usr/local/bin/pip3    /usr/bin/pip

WORKDIR /workspace
