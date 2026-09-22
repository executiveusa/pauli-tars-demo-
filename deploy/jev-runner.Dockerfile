FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
RUN pip install --no-cache-dir uv==0.8.22
WORKDIR /app
COPY jev-ultrafast /app/jev-ultrafast
RUN cd /app/jev-ultrafast && uv sync --frozen
COPY server.py /app/server.py
EXPOSE 8643
CMD ["python", "/app/server.py"]
