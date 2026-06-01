# ============================================================
# SenSa FastAPI generator 이미지 (C-1)
#   - 배치 경로: ~/SenSa/fastapi_generator/Dockerfile
#   - 경량 서비스(requirements.txt 33줄). main.py __main__ 이 uvicorn 0.0.0.0:8001 기동.
# ============================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt

COPY . /app

EXPOSE 8001

# main.py 의 __main__ 진입점이 uvicorn.run(host=0.0.0.0, port=8001) 수행
CMD ["python", "main.py"]
