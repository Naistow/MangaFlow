FROM python:3.11-slim
WORKDIR /app
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server /app/server
COPY core/auth.py /app/core/auth.py
COPY database /app/database
COPY admin_invites.py /app/admin_invites.py
RUN useradd --uid 10001 --create-home mangaflow && mkdir -p /data && chown mangaflow /data
USER mangaflow
ENV MF_AUTH_DB=/data/auth.db
EXPOSE 8000
CMD ["uvicorn", "server.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--no-proxy-headers"]
