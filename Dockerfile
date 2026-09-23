FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY stagegen ./stagegen
RUN useradd --uid 10001 --create-home stage && mkdir /data && chown stage:stage /data
USER stage
ENV STAGE_DATA_DIR=/data
EXPOSE 8000
CMD ["uvicorn", "stagegen.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
