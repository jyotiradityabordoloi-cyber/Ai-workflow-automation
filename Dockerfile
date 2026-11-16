FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN useradd --create-home app && chown -R app /app
USER app
ENV PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/healthz')"
# GROQ_API_KEY is provided by the host as a secret, never baked into the image.
CMD ["python", "server.py"]
