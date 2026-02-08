# Use Python as base image
FROM python:3.12-slim

# Run updates and install ffmpeg
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy your bot.py into the image
COPY bot.py /app/bot.py

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

ENV PATH="/opt/venv/bin:$PATH"

# Set the default command
CMD ["python", "bot.py"]
