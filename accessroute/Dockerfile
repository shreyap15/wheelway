FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY accessroute ./accessroute
COPY scripts ./scripts

EXPOSE 8000

CMD ["python", "-m", "accessroute.deploy_bureau"]
