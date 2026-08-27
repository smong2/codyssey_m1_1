import os
import sqlite3
from pathlib import Path

# DB 파일 기본 경로 (프로젝트 루트의 src/weather.db)
DEFAULT_DB_PATH = os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent / "weather.db"))

def get_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """SQLite DB 연결 객체 반환 (Row 팩토리 적용으로 딕셔너리 형태 접근 가능)"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str = DEFAULT_DB_PATH):
    """테이블 및 인덱스 초기화 생성 (IF NOT EXISTS)"""
    
    # DB 디렉토리가 없을 경우 생성
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # 1. 시간별 관측 및 파생지표 테이블
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS weather_hourly (
        stn_id TEXT NOT NULL,
        tm TEXT NOT NULL,
        ta REAL,
        hm REAL,
        ws REAL,
        ss REAL DEFAULT 0.0,
        si REAL,
        di REAL,
        cdd REAL DEFAULT 0.0,
        hdd REAL DEFAULT 0.0,
        wind_chill REAL,
        load_kw REAL,
        quality_status TEXT DEFAULT '정상',
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (stn_id, tm)
    );
    """)

    # 2. 일별 기후통계 기준선 테이블
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS climate_daily (
        stn_id TEXT NOT NULL,
        ymd TEXT NOT NULL,
        ta_avg REAL,
        ta_max REAL,
        ta_min REAL,
        rhm_avg REAL,
        rhm_min REAL,
        ss_sum REAL,
        ss_rate REAL,
        created_at TEXT DEFAULT (datetime('now', 'localtime')),
        PRIMARY KEY (stn_id, ymd)
    );
    """)

    # 3. 데이터 수집 로그 테이블
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS collection_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stn_id TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        api_type TEXT NOT NULL,
        total_count INTEGER DEFAULT 0,
        missing_count INTEGER DEFAULT 0,
        outlier_count INTEGER DEFAULT 0,
        collected_at TEXT DEFAULT (datetime('now', 'localtime'))
    );
    """)

    # 4. 조회 성능 최적화 인덱스 생성
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_weather_hourly_tm ON weather_hourly(tm);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_climate_daily_ymd ON climate_daily(ymd);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_collection_log_stn ON collection_log(stn_id, collected_at);")

    conn.commit()
    conn.close()
    print(f"✅ SQLite 데이터베이스 초기화 완료: {db_path}")

if __name__ == "__main__":
    # 스크립트 직접 실행 시 DB 초기화 수행
    init_db()