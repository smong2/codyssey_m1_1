from fastapi import APIRouter
from src.lib.db import get_connection
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/dashboard-stats")
async def get_dashboard_stats(stn: str = "108", startDate: str = None, endDate: str = None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        kst_now = datetime.utcnow() + timedelta(hours=9)
        today_str = kst_now.strftime("%Y-%m-%d")
        
        # 날짜 파라미터가 없으면 '오늘' 기준으로 기본 동작(스마트 폴백 적용)
        if not startDate or not endDate:
            cursor.execute("SELECT COUNT(*) FROM weather_hourly WHERE stn_id = ? AND tm LIKE ?", (stn, f"{today_str}%"))
            today_count = cursor.fetchone()[0]

            active_start = today_str
            active_end = today_str
            is_fallback = False
            if today_count < 24:
                cursor.execute("""
                    SELECT substr(tm, 1, 10) as dt, COUNT(*) as cnt 
                    FROM weather_hourly WHERE stn_id = ? GROUP BY dt HAVING cnt = 24 ORDER BY dt DESC LIMIT 1
                """, (stn,))
                row = cursor.fetchone()
                if row:
                    active_start = row[0]
                    active_end = row[0]
                    is_fallback = (active_start != today_str)
        else:
            active_start = startDate
            active_end = endDate
            is_fallback = False

        # 1. 지정된 기간(active_start ~ active_end)의 요약 데이터 조회
        cursor.execute("""
            SELECT AVG(ta), AVG(hm), SUM(load_kw), COUNT(*) 
            FROM weather_hourly 
            WHERE stn_id = ? AND tm >= ? AND tm <= ?
        """, (stn, f"{active_start} 00:00", f"{active_end} 23:59"))
        summary = cursor.fetchone()

        # 2. 대시보드 동적 차트를 위한 일별 트렌드 데이터 추출
        cursor.execute("""
            SELECT substr(tm, 1, 10) as ymd, SUM(load_kw) as daily_load, AVG(ta) as daily_ta
            FROM weather_hourly
            WHERE stn_id = ? AND tm >= ? AND tm <= ?
            GROUP BY substr(tm, 1, 10)
            ORDER BY ymd
        """, (stn, f"{active_start} 00:00", f"{active_end} 23:59"))
        
        daily_rows = cursor.fetchall()
        daily_trend = [
            {"ymd": row[0], "daily_load": round(row[1], 1) if row[1] else 0, "daily_ta": round(row[2], 1) if row[2] else 0} 
            for row in daily_rows
        ]

        # 3. 전체 DB 누적 통계
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT stn_id) FROM weather_hourly")
        total_records, total_stations = cursor.fetchone()

        # 4. 관측소별 최근 수집 상태
        cursor.execute("SELECT stn_id, MAX(tm) as last_tm, COUNT(*) as cnt FROM weather_hourly GROUP BY stn_id")
        stations_status = [{"stn_id": r[0], "last_tm": r[1], "count": r[2]} for r in cursor.fetchall()]

        return {
            "today_str": today_str,
            "active_start": active_start,
            "active_end": active_end,
            "is_fallback": is_fallback,
            "total_records": total_records,
            "summary": {
                "avg_ta": round(summary[0], 1) if summary[0] else 0,
                "avg_hm": round(summary[1], 1) if summary[1] else 0,
                "total_load": round(summary[2], 1) if summary[2] else 0,
                "hours": summary[3] or 0
            },
            "daily_trend": daily_trend,
            "stations_status": stations_status
        }
    finally:
        conn.close()