FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 buddy2api \
    && mkdir -p /app/data \
    && chown -R buddy2api:buddy2api /app \
    && chmod +x /app/docker-entrypoint.sh \
    && ln -s /app/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8787

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8787"]
