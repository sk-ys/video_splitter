def format_time(seconds):
    """Format seconds to mm:ss.sss"""
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:06.3f}"


def parse_time(time_str):
    """Parse time string in seconds or mm:ss.sss format to seconds"""
    if ":" in time_str:
        parts = time_str.split(":")
        if len(parts) != 2:
            raise ValueError("Invalid time format")
        minutes = int(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds
    else:
        return float(time_str)
