import pandas as pd
from datetime import datetime, timedelta

def calculate_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """결측치/이상치 자동 정제 및 파생지표 계산 엔진"""
    if df.empty: return df
    df.columns = [str(c).upper() for c in df.columns]

    ta_series = df["TA"] if "TA" in df.columns else (df.iloc[:, 11] if df.shape[1] > 11 else None)
    hm_series = df["HM"] if "HM" in df.columns else (df.iloc[:, 13] if df.shape[1] > 13 else None)
    ws_series = df["WS"] if "WS" in df.columns else (df.iloc[:, 3] if df.shape[1] > 3 else None)
    ss_series = df["SS"] if "SS" in df.columns else (df.iloc[:, 33] if df.shape[1] > 33 else None)

    df["ta_raw"] = pd.to_numeric(ta_series, errors="coerce")
    df["hm_raw"] = pd.to_numeric(hm_series, errors="coerce")
    df["ss_raw"] = pd.to_numeric(ss_series, errors="coerce")
    df["ws_raw"] = pd.to_numeric(ws_series, errors="coerce")

    statuses = []
    for _, row in df.iterrows():
        notes = []
        # 기온 검사
        t_val = row["ta_raw"]
        if pd.isna(t_val): notes.append("기온 결측(NaN) → ffill 보정")
        elif t_val > 45.0 or t_val < -35.0: notes.append(f"기온 이상치({t_val}℃) → 임계 캡핑 보정")
            
        # 습도 검사
        h_val = row["hm_raw"]
        if pd.isna(h_val): notes.append("습도 결측(NaN) → ffill 보정")
        elif h_val > 100.0 or h_val < 0.0: notes.append(f"습도 이상치({h_val}%) → 임계 캡핑 보정")
            
        # 일조 검사
        s_val = row["ss_raw"]
        if pd.isna(s_val): notes.append("일조 결측(NaN) → 0.0 보정")
        elif s_val < 0: notes.append(f"일조 특수코드({s_val}) → 야간/미관측 0.0 보정")

        if not notes: statuses.append("정상 수집")
        else: statuses.append(" | ".join(notes))

    df["quality_status"] = statuses

    # 실제 수학적 정제 적용
    df["ta"] = df["ta_raw"].ffill().fillna(15.0).clip(lower=-35.0, upper=45.0)
    df["hm"] = df["hm_raw"].ffill().fillna(60.0).clip(lower=0.0, upper=100.0)
    df["ws"] = df["ws_raw"].fillna(0.0)
    df["ss"] = df["ss_raw"].fillna(0.0).apply(lambda x: 0.0 if x < 0 else x)

    # 파생지표
    df["di"] = 1.8 * df["ta"] - 0.55 * (1 - df["hm"] / 100.0) * (1.8 * df["ta"] - 26.0) + 32.0
    df["cdd"] = df["ta"].apply(lambda x: max(0.0, (x - 24.0) / 24.0))
    df["hdd"] = df["ta"].apply(lambda x: max(0.0, (18.0 - x) / 24.0))

    def calc_wind_chill(r):
        t, v = r["ta"], r["ws"]
        if t <= 10.0 and v >= 1.3:
            v_kmh = v * 3.6
            return 13.12 + 0.6215 * t - 11.37 * (v_kmh ** 0.16) + 0.3965 * t * (v_kmh ** 0.16)
        return t
    df["wind_chill"] = df.apply(calc_wind_chill, axis=1)
    df["load_kw"] = 100.0 + (df["cdd"] * 24.0 * 6.5) + (df["hdd"] * 24.0 * 5.0) + (df["ss"] * 4.0)

    return df

def get_shrink_range(stn: str, start_date: str, end_date: str, conn):
    """DB에 24시간 완비된 날짜를 확인하여 API 호출 범위를 축소"""
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