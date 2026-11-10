# Designer page + STL generator API
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY cad/requirements.txt cad/requirements.txt
RUN pip install --no-cache-dir -r cad/requirements.txt

COPY cad/ cad/
# Bake every font into the image so generation works offline
RUN python cad/fetch_fonts.py

COPY site/ site/
COPY server.py .

RUN useradd --system --uid 10001 app && chown -R app /app
USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1

CMD ["python", "server.py"]
