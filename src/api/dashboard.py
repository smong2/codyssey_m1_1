from fastapi import APIRouter
from src.lib.db import get_connection
from datetime import datetime, timedelta

router = APIRouter()

@router.get("/dashboard")
async def get_dashboard_stats(stn: str = "108"):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        kst_now = datetime.utcnow() + timedelta(hours=9)
        today_str = kst_now.strftime("%Y-%m-%d")

        # 1. 오늘 수집된 시간 데이터 개수 확인
        cursor.execute("""
            SELECT COUNT(*) FROM weather_hourly 
            WHERE stn_id = ? AND tm LIKE ?
        """, (stn, f"{today_str}%"))
        today_count = cursor.fetchone()[0]

        # 2. 스마트 폴백: 오늘 데이터가 없거나 부족하면 가장 최근에 24시간 완비된 날짜 탐색
        active_date = today_str
        is_fallback = False
        if today_count < 24:
            cursor.execute("""
                SELECT substr(tm, 1, 10) as dt, COUNT(*) as cnt 
                FROM weather_hourly 
                WHERE stn_id = ? 
                GROUP BY dt 
                HAVING cnt = 24 
                ORDER BY dt DESC 
                LIMIT 1
            """, (stn,))
            row = cursor.fetchone()
            if row:
                active_date = row[0]
                is_fallback = (active_date != today_str)

        # 3. 선택된 기준일(active_date)의 요약 데이터 조회
        cursor.execute("""
            SELECT AVG(ta), AVG(hm), SUM(load_kw), COUNT(*) 
            FROM weather_hourly 
            WHERE stn_id = ? AND tm LIKE ?
        """, (stn, f"{active_date}%"))
        summary = cursor.fetchone()

        # 4. 전체 DB 누적 통계
        cursor.execute("SELECT COUNT(*), COUNT(DISTINCT stn_id) FROM weather_hourly")
        total_records, total_stations = cursor.fetchone()

        # 5. 관측소별 최근 수집 상태
        cursor.execute("""
            SELECT stn_id, MAX(tm) as last_tm, COUNT(*) as cnt 
            FROM weather_hourly 
            GROUP BY stn_id
        """)
        stations_status = [{"stn_id": r[0], "last_tm": r[1], "count": r[2]} for r in cursor.fetchall()]

        return {
            "today_str": today_str,
            "active_date": active_date,
            "is_fallback": is_fallback,
            "today_collected_hours": today_count,
            "total_records": total_records,
            "summary": {
                "avg_ta": round(summary[0], 1) if summary[0] else 0,
                "avg_hm": round(summary[1], 1) if summary[1] else 0,
                "total_load": round(summary[2], 1) if summary[2] else 0,
                "hours": summary[3] or 0
            },
            "stations_status": stations_status
        }
    finally:
        conn.close()