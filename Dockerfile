FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY render_start.py ./render_start.py

RUN mkdir -p /tmp/neurophoto-cache

EXPOSE 10000
CMD ["python", "render_start.py"]
