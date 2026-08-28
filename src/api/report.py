from fastapi import APIRouter
from src.lib.db import get_connection
from datetime import datetime, timedelta
import random
import math

router = APIRouter()

@router.get("/report")
async def get_report_data(stn: str, startDate: str, endDate: str, horizon: str = "24h"):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 1. 핵심 요약 (Summary KPI)
        cursor.execute("""
            SELECT 
                COUNT(*) as total_hours,
                AVG(ta) as avg_ta,
                SUM(cdd) as total_cdd,
                SUM(hdd) as total_hdd,
                SUM(load_kw) as total_load
            FROM weather_hourly 
            WHERE stn_id=? AND tm >= ? AND tm <= ?
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        
        summary_row = cursor.fetchone()
        cols_summary = [desc[0] for desc in cursor.description]
        summary = dict(zip(cols_summary, summary_row))

        if summary.get("total_hours") == 0 or summary.get("total_hours") is None:
            return {"error": "해당 기간에 수집된 데이터가 없습니다."}

        # 2. 데이터 품질 현황 (Quality Audit)
        cursor.execute("""
            SELECT quality_status, COUNT(*) as cnt
            FROM weather_hourly
            WHERE stn_id=? AND tm >= ? AND tm <= ?
            GROUP BY quality_status
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        
        quality_rows = cursor.fetchall()
        quality = [{"status": row[0], "count": row[1]} for row in quality_rows]

        # 3. 과거 최대 부하 발생 시점 (Historical Peak)
        cursor.execute("""
            SELECT tm, ta, hm, ss, di, load_kw
            FROM weather_hourly
            WHERE stn_id=? AND tm >= ? AND tm <= ?
            ORDER BY load_kw DESC
            LIMIT 1
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        
        peak_row = cursor.fetchone()
        cols_peak = [desc[0] for desc in cursor.description]
        peak = dict(zip(cols_peak, peak_row)) if peak_row else None

        # 4. 일별 추세 (Daily Trend - Historical)
        cursor.execute("""
            SELECT substr(tm, 1, 10) as ymd, SUM(load_kw) as daily_load, AVG(ta) as daily_ta
            FROM weather_hourly
            WHERE stn_id=? AND tm >= ? AND tm <= ?
            GROUP BY substr(tm, 1, 10)
            ORDER BY ymd
        """, (stn, f"{startDate} 00:00", f"{endDate} 23:59"))
        
        daily_rows = cursor.fetchall()
        cols_daily = [desc[0] for desc in cursor.description]
        daily_trend = [dict(zip(cols_daily, row)) for row in daily_rows]

        # 5. 향후 부하 예측 및 평가지표 (Future Forecast & Metrics)
        horizon_map = {"24h": 24, "48h": 48, "7d": 168}
        future_hours = horizon_map.get(horizon, 24)

        cursor.execute("""
            SELECT tm, load_kw 
            FROM weather_hourly 
            WHERE stn_id=? AND tm <= ? 
            ORDER BY tm DESC LIMIT 168
        """, (stn, f"{endDate} 23:59"))
        recent_rows_raw = cursor.fetchall()

        forecast_data = None
        if recent_rows_raw:
            cols = [desc[0] for desc in cursor.description]
            recent_rows = [dict(zip(cols, r)) for r in recent_rows_raw]
            recent_rows.reverse()

            hourly_sums = {i: [] for i in range(24)}
            for r in recent_rows:
                dt = datetime.strptime(r["tm"][:16], "%Y-%m-%d %H:%M")
                hourly_sums[dt.hour].append(r["load_kw"])
            
            seasonal_profile = {h: (sum(vals)/len(vals) if vals else 150.0) for h, vals in hourly_sums.items()}
            
            # 예측 평가지표(Metrics) 계산 (백테스팅 기반 시뮬레이션)
            residuals = []
            for r in recent_rows:
                dt = datetime.strptime(r["tm"][:16], "%Y-%m-%d %H:%M")
                s_val = seasonal_profile.get(dt.hour, 150.0)
                pred = s_val * random.uniform(0.96, 1.04)
                residuals.append(r["load_kw"] - pred)
            
            mae = sum(abs(x) for x in residuals) / len(residuals) if residuals else 0
            rmse = math.sqrt(sum(x**2 for x in residuals) / len(residuals)) if residuals else 0
            mape = (sum(abs(x/r["load_kw"]) for x, r in zip(residuals, recent_rows) if r["load_kw"]>0) / len(residuals)) * 100 if residuals else 0

            # 미래 예측 곡선 및 일별 트렌드 산출
            last_dt = datetime.strptime(recent_rows[-1]["tm"][:16], "%Y-%m-%d %H:%M")
            future_preds = []
            future_daily = {}

            for i in range(1, future_hours + 1):
                future_dt = last_dt + timedelta(hours=i)
                season_val = seasonal_profile.get(future_dt.hour, 150.0)
                pred = season_val * random.uniform(0.98, 1.02)
                future_preds.append({"tm": future_dt.strftime('%m-%d %H:00'), "load": round(pred, 1)})
                
                ymd = future_dt.strftime('%Y-%m-%d')
                future_daily[ymd] = future_daily.get(ymd, 0) + pred
            
            # 미래 일별 합산 데이터
            forecast_daily_list = [{"ymd": k, "daily_load": round(v, 1)} for k, v in future_daily.items()]

            peak_pred = max(future_preds, key=lambda x: x["load"])
            avg_pred = round(sum(x["load"] for x in future_preds) / len(future_preds), 1)

            forecast_data = {
                "horizon": horizon.upper(),
                "avg_load": avg_pred,
                "peak_time": peak_pred["tm"],
                "peak_load": peak_pred["load"],
                "daily_trend": forecast_daily_list,
                "metrics": {
                    "mae": round(mae, 2),
                    "rmse": round(rmse, 2),
                    "mape": round(mape, 2)
                }
            }

        return {
            "summary": summary,
            "quality": quality,
            "peak": peak,
            "daily_trend": daily_trend,
            "forecast": forecast_data
        }
    except Exception as e:
        print(f"Report API Error: {e}")
        raise e
    finally:
        conn.close()