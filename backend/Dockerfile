FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# requirements.txt is generated from the root uv.lock with `uv export`.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
