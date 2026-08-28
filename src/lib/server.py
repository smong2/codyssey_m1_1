from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.lib.db import init_db
from src.api import collect, view, eda, predict, report  # report 추가

app = FastAPI(title="WeatherLoad API")

# 서버 기동 시 DB 초기화
init_db()

# 모듈화된 API 라우터 등록
app.include_router(collect.router, prefix="/api/weather", tags=["Collect"])
app.include_router(view.router, prefix="/api/weather", tags=["View"])
app.include_router(eda.router, prefix="/api/weather", tags=["EDA"])
app.include_router(predict.router, prefix="/api/weather", tags=["Predict"])
app.include_router(report.router, prefix="/api/weather", tags=["Report"]) # 신규 라우터 등록

# 프론트엔드 HTML 서빙
@app.get("/data.html")
async def read_data():
    return FileResponse("src/data.html")

@app.get("/eda.html")
async def read_eda():
    return FileResponse("src/eda.html")

@app.get("/predict.html")
async def read_predict():
    return FileResponse("src/predict.html")

@app.get("/report.html") # 리포트 페이지 서빙
async def read_report():
    return FileResponse("src/report.html")

@app.get("/")
async def read_index():
    return FileResponse("src/index.html")

# 기타 정적 자원
app.mount("/", StaticFiles(directory="src", html=True), name="static")