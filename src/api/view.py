from fastapi import APIRouter
from src.lib.db import get_connection

router = APIRouter()

@router.get("/calendar")
async def get_calendar_data(stn: str, year_month: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT substr(tm, 1, 10) as dt, COUNT(*) as cnt 
            FROM weather_hourly 
            WHERE stn_id = ? AND tm LIKE ?
            GROUP BY dt
        """, (stn, f"{year_month}-%"))
        
        # 튜플/딕셔너리 등 DB 설정 환경과 무관하게 안전하게 매핑 (row[0]=dt, row[1]=cnt)
        return {row[0]: row[1] for row in cursor.fetchall()}
    finally:
        conn.close()

@router.get("/view")
async def view_weather_data(stn: str, date: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 시간 상세
        cursor.execute("SELECT * FROM weather_hourly WHERE stn_id=? AND tm LIKE ? ORDER BY tm", (stn, f"{date} %"))
        cols_hourly = [desc[0] for desc in cursor.description]
        hourly = [dict(zip(cols_hourly, row)) for row in cursor.fetchall()]
        
        # 일별 기후
        cursor.execute("SELECT * FROM climate_daily WHERE stn_id=? AND ymd=?", (stn, date))
        cols_daily = [desc[0] for desc in cursor.description]
        daily_rows = cursor.fetchall()
        daily = [dict(zip(cols_daily, row)) for row in daily_rows]
        
        return {"hourly": hourly, "daily": daily[0] if daily else None}
    finally:
        conn.close()