FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 필수 패키지 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 의존성 설치
COPY docker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 기본 환경변수 설정
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 서비스 포트 개방
EXPOSE 8000

# 서버 실행 (FastAPI 개발 서버: 핫 리로드 활성화)
CMD ["uvicorn", "src.lib.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]