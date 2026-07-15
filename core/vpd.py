import math


def calculate_vpd(temp_c, humidity_percent):
    try:
        svp = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
        avp = svp * (humidity_percent / 100.0)
        return round(svp - avp, 3)
    except Exception:
        return 0


def get_vpd_status(vpd):
    if 0.8 <= vpd <= 1.2:
        return "optimal"
    elif 0.4 <= vpd <= 1.6:
        return "warning"
    return "critical"


def get_moisture_status(moisture_pct):
    if 40 <= moisture_pct <= 60:
        return "optimal"
    elif 20 <= moisture_pct <= 80:
        return "warning"
    return "critical"
