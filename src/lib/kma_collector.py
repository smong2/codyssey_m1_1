import os
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

COLUMN_PRESETS = {
    "hourly": [
        "TM", "STN", "WD", "WS", "GST_WD", "GST_WS", "GST_TM", 
        "PA", "PS", "PT", "PR", "TA", "TD", "HM", "PV", 
        "RN", "RN_DAY", "RN_JUN", "RN_INT", "SD_HR3", "SD_DAY", "SD_TOT", 
        "WC", "WP", "WW", "CA_TOT", "CA_MID", "CH_MIN", "CT", "CT_TOP", 
        "CT_MID", "CT_LOW", "VS", "SS", "SI", "ST_GD", "TS"
    ],
    "temperature": [
        "YMD", "STN_ID", "LAT", "LON", "ALTD", 
        "TA_DAVG", "TMX_DD", "TMX_OCUR_TMA", "TMN_DD", "TMN_OCUR_TMA",
        "MRNG_TMN", "MRNG_TMN_OCUR_TMA", "DYTM_TMX", "DYTM_TMX_OCUR_TMA", 
        "NGHT_TMN", "NGHT_TMN_OCUR_TMA"
    ],
    "humidity": [
        "TMA", "STN_ID", "LAT", "LON", "ALTD", 
        "RHM_AVG", "RHM_MIN", "RHM_MIN_OCUR_TMA"
    ],
    "sunshine": ["TM", "STN", "LAT", "LON", "ALTD", "SS_SUM", "SS_RATE"]
}

API_CONFIG = {
    "hourly": {
        "endpoint": os.getenv("ENDPOINT_HOURLY", "/kma_sfctm3.php"),
        "stn_param": "stn",
        "is_hourly": True,
        "extra_params": {"help": "0"}
    },
    "humidity": {
        "endpoint": os.getenv("ENDPOINT_RHM", "/sts_rhm.php"),
        "stn_param": "stn_id",
        "is_hourly": False,
        "extra_params": {"help": "0", "disp": "1"}
    },
    "temperature": {
        "endpoint": os.getenv("ENDPOINT_TA", "/sts_ta.php"),
        "stn_param": "stn_id",
        "is_hourly": False,
        "extra_params": {"help": "0", "disp": "1"}
    },
    "sunshine": {
        "endpoint": os.getenv("ENDPOINT_SS", "/sts_ss.php"),
        "stn_param": "stn_id",
        "is_hourly": False,
        "extra_params": {"help": "0", "disp": "1"}
    }
}

def parse_typ01_to_dataframe(raw_text: str, api_type: str = "hourly") -> pd.DataFrame:
    lines = raw_text.strip().split('\n')
    data_lines = []
    header_columns = []

    for line in lines:
        # ✅ 데이터 끝에 붙는 '=' 구분자 일괄 제거
        line = line.replace('=', '').strip()
        
        if not line or line.startswith("#7777"):
            continue

        if line.startswith("#"):
            parts = line.replace("#", "").strip().split()
            if any(key in parts for key in ["TM", "YMD", "TA", "STN", "TA_DAVG", "RHM_AVG", "SS_SUM"]):
                header_columns = [p.upper() for p in parts]
        else:
            data_lines.append(line.split())

    if not data_lines:
        return pd.DataFrame()

    df = pd.DataFrame(data_lines)
    preset = COLUMN_PRESETS.get(api_type, [])
    
    if header_columns and len(header_columns) == df.shape[1]:
        df.columns = header_columns
    elif preset and len(preset) <= df.shape[1]:
        df.columns = preset + [f"EXTRA_{i}" for i in range(len(preset), df.shape[1])]
    elif preset:
        df.columns = preset[:df.shape[1]]
    else:
        df.columns = [f"COL_{i}" for i in range(df.shape[1])]

    return df

def fetch_kma_data(api_type: str, start_date: str, end_date: str, stn: str = "108") -> pd.DataFrame:
    config = API_CONFIG[api_type]
    base_url = os.getenv("KMA_BASE_URL", "https://apihub.kma.go.kr/api/typ01/url")
    api_key = os.getenv("KMA_API_KEY")

    start_clean = start_date.replace("-", "")
    end_clean = end_date.replace("-", "")

    if config["is_hourly"]:
        tm1 = f"{start_clean}0000"
        tm2 = f"{end_clean}2300"
    else:
        tm1 = start_clean
        tm2 = end_clean

    params = {"tm1": tm1, "tm2": tm2, config["stn_param"]: stn, "authKey": api_key}
    params.update(config["extra_params"])

    response = requests.get(f"{base_url}{config['endpoint']}", params=params, timeout=15)
    if response.status_code != 200:
        raise Exception(f"기상청 API 요청 실패 (HTTP {response.status_code})")

    return parse_typ01_to_dataframe(response.text, api_type=api_type)