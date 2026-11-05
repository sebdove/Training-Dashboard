FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY web ./web
COPY data/*.example.json ./data/
ENV T100_HOST=0.0.0.0 \
    T100_PORT=8100 \
    T100_DATA_DIR=/data \
    GARMINTOKENS=/data/.garminconnect
VOLUME ["/data"]
EXPOSE 8100
CMD ["python", "server/app.py"]
