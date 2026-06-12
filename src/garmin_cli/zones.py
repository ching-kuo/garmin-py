"""Training-zone calculations.

Pure functions — no Garmin API dependency.
"""
from __future__ import annotations


def ms_to_pace(speed_ms: float) -> str:
    """Convert speed in m/s to a pace string in min:sec /km."""
    if not speed_ms or speed_ms <= 0:
        return "N/A"
    total_seconds = 1000.0 / speed_ms
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    return f"{minutes}:{seconds:02d} /km"


def calculate_running_zones(lt_pace_ms: float) -> dict[str, dict[str, str]]:
    """Return running pace zones based on lactate-threshold pace (m/s)."""
    return {
        "Zone 1 (Recovery)": {
            "description": "Easy / Recovery",
            "pace_range": f"slower than {ms_to_pace(lt_pace_ms * 0.775)}",
            "effort": "very easy, conversational",
        },
        "Zone 2 (Aerobic)": {
            "description": "Aerobic / Base",
            "pace_range": (
                f"{ms_to_pace(lt_pace_ms * 0.775)} – "
                f"{ms_to_pace(lt_pace_ms * 0.877)}"
            ),
            "effort": "comfortable, can speak in sentences",
        },
        "Zone 3 (Tempo)": {
            "description": "Tempo",
            "pace_range": (
                f"{ms_to_pace(lt_pace_ms * 0.877)} – "
                f"{ms_to_pace(lt_pace_ms * 0.943)}"
            ),
            "effort": "comfortably hard, short sentences only",
        },
        "Zone 4 (Threshold)": {
            "description": "Lactate Threshold",
            "pace_range": (
                f"{ms_to_pace(lt_pace_ms * 0.943)} – "
                f"{ms_to_pace(lt_pace_ms * 1.01)}"
            ),
            "effort": "hard, few words at a time",
        },
        "Zone 5 (VO2max)": {
            "description": "VO2max / Interval",
            "pace_range": f"faster than {ms_to_pace(lt_pace_ms * 1.01)}",
            "effort": "very hard, cannot speak",
        },
    }


def calculate_cycling_zones(ftp_watts: int) -> dict[str, str]:
    """Return cycling power zones based on FTP (watts)."""
    return {
        "Zone 1 (Active Recovery)": f"< {int(ftp_watts * 0.55)} W",
        "Zone 2 (Endurance)": f"{int(ftp_watts * 0.55)} – {int(ftp_watts * 0.75)} W",
        "Zone 3 (Tempo)": f"{int(ftp_watts * 0.76)} – {int(ftp_watts * 0.90)} W",
        "Zone 4 (Threshold)": f"{int(ftp_watts * 0.91)} – {int(ftp_watts * 1.05)} W",
        "Zone 5 (VO2max)": f"{int(ftp_watts * 1.06)} – {int(ftp_watts * 1.20)} W",
        "Zone 6 (Anaerobic)": f"> {int(ftp_watts * 1.20)} W",
    }


def classify_running_step(step: dict, lt_pace_ms: float) -> str:
    """Classify a running workout step into a zone based on LT pace."""
    target_range = step.get("target_range", [None, None])
    if not target_range[0] or not target_range[1]:
        return "Unknown zone"

    mid_speed = (float(target_range[0]) + float(target_range[1])) / 2
    ratio = mid_speed / lt_pace_ms

    if ratio < 0.775:
        return "Zone 1 (Recovery)"
    elif ratio < 0.877:
        return "Zone 2 (Aerobic)"
    elif ratio < 0.943:
        return "Zone 3 (Tempo)"
    elif ratio < 1.01:
        return "Zone 4 (Threshold)"
    else:
        return "Zone 5 (VO2max)"
