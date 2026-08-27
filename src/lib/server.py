import os
import pandas as pd
from datetime import datetime, timedelta
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from src.lib.kma_collector import fetch_kma_data
from src.lib.db import init_db, get_connection
from pydantic import BaseModel

app = FastAPI(title="WeatherLoad API")
init_db()

class CollectRequest(BaseModel):
    startDate: str
    endDate: str
    stn: str

# ─── 정제 정책 1: 원본 상태 기록 및 파생지표 계산 ───
def calculate_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    df.columns = [str(c).upper() for c in df.columns]

    ta_series = df["TA"] if "TA" in df.columns else (df.iloc[:, 11] if df.shape[1] > 11 else None)
    hm_series = df["HM"] if "HM" in df.columns else (df.iloc[:, 13] if df.shape[1] > 13 else None)
    ws_series = df["WS"] if "WS" in df.columns else (df.iloc[:, 3] if df.shape[1] > 3 else None)
    ss_series = df["SS"] if "SS" in df.columns else (df.iloc[:, 33] if df.shape[1] > 33 else None)

    df["ta_raw"] = pd.to_numeric(ta_series, errors="coerce")
    df["hm_raw"] = pd.to_numeric(hm_series, errors="coerce")

    # 1. 원본 품질 상태 판정
    def eval_quality(row):
        if pd.isna(row["ta_raw"]) or pd.isna(row["hm_raw"]): return "결측"
        if row["ta_raw"] > 45.0 or row["ta_raw"] < -35.0 or row["hm_raw"] > 100.0 or row["hm_raw"] < 0.0: return "이상"
        return "정상"
    
    df["orig_quality"] = df.apply(eval_quality, axis=1)

    # 2. 정제(결측치 대치 및 이상치 캡핑)
    df["ta"] = df["ta_raw"].ffill().fillna(15.0).clip(lower=-35.0, upper=45.0)
    df["hm"] = df["hm_raw"].ffill().fillna(60.0).clip(lower=0.0, upper=100.0)
    df["ws"] = pd.to_numeric(ws_series, errors="coerce").fillna(0.0)
    df["ss"] = pd.to_numeric(ss_series, errors="coerce").fillna(0.0)

    # 3. 파생지표 생성
    df["di"] = 1.8 * df["ta"] - 0.55 * (1 - df["hm"] / 100.0) * (1.8 * df["ta"] - 26.0) + 32.0
    df["cdd"] = df["ta"].apply(lambda x: max(0.0, (x - 24.0) / 24.0))
    df["hdd"] = df["ta"].apply(lambda x: max(0.0, (18.0 - x) / 24.0))

    def calc_wind_chill(row):
        t, v = row["ta"], row["ws"]
        if t <= 10.0 and v >= 1.3:
            v_kmh = v * 3.6
            return 13.12 + 0.6215 * t - 11.37 * (v_kmh ** 0.16) + 0.3965 * t * (v_kmh ** 0.16)
        return t
    df["wind_chill"] = df.apply(calc_wind_chill, axis=1)
    df["load_kw"] = 100.0 + (df["cdd"] * 24.0 * 6.5) + (df["hdd"] * 24.0 * 5.0) + (df["ss"] * 4.0)

    # 4. 최종 저장용 텍스트 생성 (예: "결측 → 전방대치")
    def set_final_status(row):
        if row["orig_quality"] == "결측": return "결측 → 전방대치"
        if row["orig_quality"] == "이상": return "이상 → 임계보정"
        return "정상"
        
    df["quality_status"] = df.apply(set_final_status, axis=1)
    return df

# ─── 구간 축소(Shrink) 캐싱 알고리즘 ───
def get_shrink_range(stn: str, start_date: str, end_date: str, conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT substr(tm, 1, 10) as dt, COUNT(*) as cnt 
        FROM weather_hourly 
        WHERE stn_id = ? AND tm >= ? AND tm <= ?
        GROUP BY dt
    """, (stn, f"{start_date} 00:00", f"{end_date} 23:59"))
    
    complete_dates = {row[0] for row in cursor.fetchall() if row[1] == 24}

    cur_start = datetime.strptime(start_date, "%Y-%m-%d")
    cur_end = datetime.strptime(end_date, "%Y-%m-%d")

    while cur_start <= cur_end and cur_start.strftime("%Y-%m-%d") in complete_dates:
        cur_start += timedelta(days=1)
    
    while cur_end >= cur_start and cur_end.strftime("%Y-%m-%d") in complete_dates:
        cur_end -= timedelta(days=1)

    if cur_start > cur_end:
        return None, None
    return cur_start.strftime("%Y-%m-%d"), cur_end.strftime("%Y-%m-%d")


@app.post("/api/weather/collect-all")
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

        cursor.execute("SELECT * FROM weather_hourly WHERE stn_id=? AND tm >= ? AND tm <= ? ORDER BY tm", 
                       (req.stn, f"{req.startDate} 00:00", f"{req.endDate} 23:59"))
        hourly_data = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT * FROM climate_daily WHERE stn_id=? AND ymd >= ? AND ymd <= ? ORDER BY ymd", 
                       (req.stn, req.startDate, req.endDate))
        daily_data = [dict(row) for row in cursor.fetchall()]

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

@app.get("/api/weather/calendar")
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
        return {row["dt"]: row["cnt"] for row in cursor.fetchall()}
    finally:
        conn.close()

@app.get("/api/weather/view")
async def view_weather_data(stn: str, date: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM weather_hourly WHERE stn_id=? AND tm LIKE ? ORDER BY tm", (stn, f"{date} %"))
        hourly = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT * FROM climate_daily WHERE stn_id=? AND ymd=?", (stn, date))
        daily = [dict(row) for row in cursor.fetchall()]
        
        return {"hourly": hourly, "daily": daily[0] if daily else None}
    finally:
        conn.close()

@app.get("/")
async def read_index():
    return FileResponse("src/index.html")

app.mount("/", StaticFiles(directory="src", html=True), name="static")