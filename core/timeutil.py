import utime
import ntptime


def is_dst_europe(dt):
    """EU DST: last Sunday of March 02:00 UTC to last Sunday of October 03:00 CEST.
    dt is a utime.localtime() tuple: (year, month, day, hour, minute, second, weekday, yearday)."""
    month, day, weekday = dt[1], dt[2], dt[6]
    if 3 < month < 10:
        return True
    if month < 3 or month > 10:
        return False
    last_sunday = day + (6 - weekday) > 31
    if month == 3:
        return last_sunday
    return not last_sunday  # month == 10


def localtime_with_offset():
    tz_offset = (2 if is_dst_europe(utime.localtime()) else 1) * 3600
    return utime.localtime(utime.time() + tz_offset)


def format_datetime(dt):
    return "{:04d}/{:02d}/{:02d}-{:02d}:{:02d}:{:02d}".format(
        dt[0], dt[1], dt[2], dt[3], dt[4], dt[5])


def sync_time():
    try:
        ntptime.settime()
        print("Zeit synchronisiert:", format_datetime(localtime_with_offset()))
        return True
    except Exception:
        return False
