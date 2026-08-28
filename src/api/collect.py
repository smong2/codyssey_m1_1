from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.lib.db import get_connection
from src.lib.kma_collector import fetch_kma_data
from src.lib.processor import get_shrink_range, calculate_derived_metrics

router = APIRouter()

class CollectRequest(BaseModel):
    startDate: str
    endDate: str
    stn: str

@router.post("/collect-all")
async def collect_all_weather_data(req: CollectRequest):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        fetch_start, fetch_end = get_shrink_range(req.stn, req.startDate, req.endDate, conn)
        fetched_hourly_count = 0
        fetched_daily_count = 0

        if fetch_start and fetch_end:
            df_hourly = fetch_kma_data("hourly", fetch_start, fetch_end, req.stn)
            df_ta = fetch_kma_data("temperature", fetch_start, fetch_end, req.stn)
            df_rhm = fetch_kma_data("humidity", fetch_start, fetch_end, req.stn)
            df_ss = fetch_kma_data("sunshine", fetch_start, fetch_end, req.stn)

            if not df_hourly.empty:
                df_hourly = calculate_derived_metrics(df_hourly)
                for _, row in df_hourly.iterrows():
                    raw_tm = str(row.get("TM", ""))
                    tm_fmt = f"{raw_tm[:4]}-{raw_tm[4:6]}-{raw_tm[6:8]} {raw_tm[8:10]}:00" if len(raw_tm) >= 10 else raw_tm
                    cursor.execute("""
                        INSERT OR REPLACE INTO weather_hourly 
                        (stn_id, tm, ta, hm, ws, ss, di, cdd, hdd, wind_chill, load_kw, quality_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        req.stn, tm_fmt, 
                        round(float(row["ta"]),1), round(float(row["hm"]),1), round(float(row["ws"]),1), round(float(row["ss"]),1),
                        round(float(row["di"]),1), round(float(row["cdd"]),3), round(float(row["hdd"]),3),
                        round(float(row["wind_chill"]),1), round(float(row["load_kw"]),1), row["quality_status"]
                    ))
                    fetched_hourly_count += 1

            climate_dict = {}
            if not df_ta.empty:
                for _, r in df_ta.iterrows():
                    ymd = str(r.get("YMD", r.get("TM", r.get(0, ""))))
                    if len(ymd) >= 8:
                        ymd_fmt = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
                        val_avg = float(r.get("TA_DAVG", r.get(5))) if r.get("TA_DAVG", r.get(5)) not in ["", None, "-99"] else None
                        val_max = float(r.get("TMX_DD", r.get(6))) if r.get("TMX_DD", r.get(6)) not in ["", None, "-99"] else None
                        val_min = float(r.get("TMN_DD", r.get(8))) if r.get("TMN_DD", r.get(8)) not in ["", None, "-99"] else None
                        if val_min is not None and val_max is not None and val_min > val_max:
                            val_min, val_max = val_max, val_min
                        climate_dict.setdefault(ymd_fmt, {})["ta_avg"] = val_avg
                        climate_dict[ymd_fmt]["ta_max"] = val_max
                        climate_dict[ymd_fmt]["ta_min"] = val_min

            if not df_rhm.empty:
                for _, r in df_rhm.iterrows():
                    raw_tma = str(r.get("TMA", r.get("TM", r.get(0, ""))))
                    if len(raw_tma) >= 8:
                        ymd_fmt = f"{raw_tma[:4]}-{raw_tma[4:6]}-{raw_tma[6:8]}"
                        val_avg = float(r.get("RHM_AVG", r.get(5))) if r.get("RHM_AVG", r.get(5)) not in ["", None, "-99"] else None
                        val_min = float(r.get("RHM_MIN", r.get(6))) if r.get("RHM_MIN", r.get(6)) not in ["", None, "-99"] else None
                        if val_avg and val_avg > 100.0: val_avg = 100.0
                        climate_dict.setdefault(ymd_fmt, {})["rhm_avg"] = val_avg
                        climate_dict[ymd_fmt]["rhm_min"] = val_min

            if not df_ss.empty:
                for _, r in df_ss.iterrows():
                    raw_tma = str(r.get("TMA", r.get("TM", r.get(0, ""))))
                    if len(raw_tma) >= 8:
                        ymd_fmt = f"{raw_tma[:4]}-{raw_tma[4:6]}-{raw_tma[6:8]}"
                        val_sum = float(r.get("SS_SUM", r.get(5))) if r.get("SS_SUM", r.get(5)) not in ["", None, "-99"] else None
                        val_rate = float(r.get("SS_RATE", r.get(6))) if r.get("SS_RATE", r.get(6)) not in ["", None, "-99"] else None
                        if val_rate and val_rate > 100.0: val_rate = 100.0
                        climate_dict.setdefault(ymd_fmt, {})["ss_sum"] = val_sum
                        climate_dict[ymd_fmt]["ss_rate"] = val_rate

            for ymd, metrics in climate_dict.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO climate_daily 
                    (stn_id, ymd, ta_avg, ta_max, ta_min, rhm_avg, rhm_min, ss_sum, ss_rate)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.stn, ymd, metrics.get("ta_avg"), metrics.get("ta_max"), metrics.get("ta_min"), 
                    metrics.get("rhm_avg"), metrics.get("rhm_min"), metrics.get("ss_sum"), metrics.get("ss_rate")
                ))
                fetched_daily_count += 1
            
            cursor.execute("""
                INSERT INTO collection_log (stn_id, start_date, end_date, api_type, total_count)
                VALUES (?, ?, ?, 'all_integrated', ?)
            """, (req.stn, fetch_start, fetch_end, fetched_hourly_count))
            
            conn.commit()

        # 결과 조회 (컬럼명을 동적으로 가져와서 안전하게 매핑)
        cursor.execute("SELECT * FROM weather_hourly WHERE stn_id=? AND tm >= ? AND tm <= ? ORDER BY tm", 
                       (req.stn, f"{req.startDate} 00:00", f"{req.endDate} 23:59"))
        cols_hourly = [desc[0] for desc in cursor.description]
        hourly_data = [dict(zip(cols_hourly, row)) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM climate_daily WHERE stn_id=? AND ymd >= ? AND ymd <= ? ORDER BY ymd", 
                       (req.stn, req.startDate, req.endDate))
        cols_daily = [desc[0] for desc in cursor.description]
        daily_data = [dict(zip(cols_daily, row)) for row in cursor.fetchall()]

        return {
            "status": "success",
            "api_called": bool(fetch_start),
            "shrink_range": [fetch_start, fetch_end] if fetch_start else None,
            "hourly_data": hourly_data,
            "daily_data": daily_data
        }

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()