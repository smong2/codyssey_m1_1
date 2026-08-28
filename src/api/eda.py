from fastapi import APIRouter
from src.lib.db import get_connection

router = APIRouter()

@router.get("/eda")
async def get_eda_data(stn: str, startDate: str, endDate: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT tm, ta, hm, ss, di, cdd, hdd, load_kw 
            FROM weather_hourly 
            WHERE stn_id=? AND tm >= ? AND tm <= ? 
            ORDER BY tm
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        cols_h = [desc[0] for desc in cursor.description]
        hourly = [dict(zip(cols_h, row)) for row in cursor.fetchall()]

        cursor.execute("""
            SELECT 
                substr(tm, 1, 10) as ymd,
                AVG(ta) as avg_ta,
                MAX(ta) as max_ta,
                SUM(cdd) as sum_cdd,
                SUM(hdd) as sum_hdd,
                SUM(load_kw) as sum_load
            FROM weather_hourly
            WHERE stn_id=? AND tm >= ? AND tm <= ?
            GROUP BY substr(tm, 1, 10)
            ORDER BY ymd
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        cols_d = [desc[0] for desc in cursor.description]
        daily_agg = [dict(zip(cols_d, row)) for row in cursor.fetchall()]

        return {"hourly": hourly, "daily": daily_agg}
    finally:
        conn.close()