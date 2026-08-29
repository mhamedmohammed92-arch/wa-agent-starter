FROM python:3.12-slim

# Unbuffered output so container logs appear immediately, and no .pyc clutter.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first: this layer is cached and only rebuilds when the file
# changes, so editing faq.json or the code does not reinstall anything.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. If this container is ever reachable from the internet
# (it is - that is the point of a webhook), root inside it is a needless risk.
RUN useradd --create-home --uid 10001 agent && chown -R agent:agent /app
USER agent

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
