"""
Workout planning utilities for race-equivalent pacing and interval calculation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from gap_calculator import METERS_PER_MILE, gap_adjustment_factor

# Race distance reference (meters)
RACE_DISTANCES_M: Dict[str, float] = {
    "800m": 800.0,
    "1500m": 1500.0,
    "1 mile": METERS_PER_MILE,
    "3k": 3000.0,
    "5k": 5000.0,
    "10k": 10000.0,
    "15k": 15000.0,
    "half marathon": 21097.5,
    "marathon": 42195.0,
    "50k": 50000.0,
}

RACE_LABEL_ALIASES: Dict[str, str] = {
    "800": "800m",
    "800m": "800m",
    "1500": "1500m",
    "1500m": "1500m",
    "mile": "1 mile",
    "1 mile": "1 mile",
    "1mi": "1 mile",
    "3k": "3k",
    "5k": "5k",
    "10k": "10k",
    "15k": "15k",
    "half": "half marathon",
    "hm": "half marathon",
    "half marathon": "half marathon",
    "marathon": "marathon",
    "full": "marathon",
    "50k": "50k",
}

RIEGEL_EXPONENT = 1.06

EFFORT_MULTIPLIERS = {
    "easy": 1.20,
    "recovery": 1.30,
    "steady": 1.10,
}


@dataclass
class IntervalSpec:
    name: str
    kind: str
    length_type: str  # "distance" or "duration"
    length_value: float
    length_unit: str  # "mi", "km", "m", or "time" for duration
    pace_source: str  # "manual", "race", "effort"
    pace_value: str  # manual pace string or race/effort label
    incline_pct: Optional[float] = None  # treadmill incline override


@dataclass
class IntervalResult:
    name: str
    kind: str
    distance_m: float
    duration_s: float
    target_gap_pace_s: float
    treadmill_pace_s: float
    pace_unit: str
    effective_incline_pct: float


def time_str_to_seconds(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + int(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    raise ValueError(f"Invalid time format: {value}. Expected mm:ss or h:mm:ss")


def seconds_to_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def pace_str_to_seconds(pace_str: str) -> float:
    parts = pace_str.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    raise ValueError(f"Invalid pace format: {pace_str}. Expected mm:ss")


def seconds_to_pace(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def normalize_race_label(label: str) -> str:
    key = label.strip().lower()
    if key in RACE_LABEL_ALIASES:
        return RACE_LABEL_ALIASES[key]
    raise ValueError(f"Unknown race label: {label}")


def distance_to_meters(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit == "mi":
        return value * METERS_PER_MILE
    if unit == "km":
        return value * 1000.0
    if unit == "m":
        return value
    raise ValueError(f"Unsupported distance unit: {unit}")


def meters_to_distance(meters: float, unit: str) -> float:
    unit = unit.lower()
    if unit == "mi":
        return meters / METERS_PER_MILE
    if unit == "km":
        return meters / 1000.0
    if unit == "m":
        return meters
    raise ValueError(f"Unsupported distance unit: {unit}")


def predict_time_riegel(base_time_s: float, base_distance_m: float, target_distance_m: float) -> float:
    return base_time_s * (target_distance_m / base_distance_m) ** RIEGEL_EXPONENT


def pace_for_distance(time_s: float, distance_m: float, pace_unit: str) -> float:
    unit_dist_m = METERS_PER_MILE if pace_unit == "mi" else 1000.0
    return time_s / (distance_m / unit_dist_m)


def get_equivalent_times(base_distance_label: str, base_time_s: float) -> Dict[str, float]:
    base_label = normalize_race_label(base_distance_label)
    base_distance_m = RACE_DISTANCES_M[base_label]
    results = {}
    for label, distance_m in RACE_DISTANCES_M.items():
        results[label] = predict_time_riegel(base_time_s, base_distance_m, distance_m)
    return results


def effort_pace_from_marathon(base_distance_label: str, base_time_s: float, effort_label: str, pace_unit: str) -> float:
    effort_key = effort_label.strip().lower()
    if effort_key not in EFFORT_MULTIPLIERS:
        raise ValueError(f"Unknown effort label: {effort_label}")
    base_label = normalize_race_label(base_distance_label)
    base_distance_m = RACE_DISTANCES_M[base_label]
    marathon_time_s = predict_time_riegel(base_time_s, base_distance_m, RACE_DISTANCES_M["marathon"])
    marathon_pace_s = pace_for_distance(marathon_time_s, RACE_DISTANCES_M["marathon"], pace_unit)
    return marathon_pace_s * EFFORT_MULTIPLIERS[effort_key]


def race_pace_from_base(base_distance_label: str, base_time_s: float, target_label: str, pace_unit: str) -> float:
    base_label = normalize_race_label(base_distance_label)
    target_norm = normalize_race_label(target_label)
    base_distance_m = RACE_DISTANCES_M[base_label]
    target_distance_m = RACE_DISTANCES_M[target_norm]
    target_time_s = predict_time_riegel(base_time_s, base_distance_m, target_distance_m)
    return pace_for_distance(target_time_s, target_distance_m, pace_unit)


def compute_interval_result(
    interval: IntervalSpec,
    base_distance_label: str,
    base_time_s: float,
    pace_unit: str,
    workout_incline_pct: float,
    treadmill_offset_pct: float,
) -> IntervalResult:
    pace_unit = pace_unit.lower()
    if pace_unit not in ("mi", "km"):
        raise ValueError("pace_unit must be 'mi' or 'km'")

    if interval.pace_source == "manual":
        target_gap_pace_s = pace_str_to_seconds(interval.pace_value)
    elif interval.pace_source == "race":
        target_gap_pace_s = race_pace_from_base(base_distance_label, base_time_s, interval.pace_value, pace_unit)
    elif interval.pace_source == "effort":
        target_gap_pace_s = effort_pace_from_marathon(base_distance_label, base_time_s, interval.pace_value, pace_unit)
    else:
        raise ValueError(f"Unsupported pace source: {interval.pace_source}")

    if interval.length_type == "distance":
        distance_m = distance_to_meters(interval.length_value, interval.length_unit)
        duration_s = target_gap_pace_s * (distance_m / (METERS_PER_MILE if pace_unit == "mi" else 1000.0))
    elif interval.length_type == "duration":
        duration_s = interval.length_value
        distance_m = duration_s / target_gap_pace_s * (METERS_PER_MILE if pace_unit == "mi" else 1000.0)
    else:
        raise ValueError(f"Unsupported length_type: {interval.length_type}")

    incline_pct = interval.incline_pct if interval.incline_pct is not None else workout_incline_pct
    effective_incline_pct = incline_pct - treadmill_offset_pct
    adjustment = gap_adjustment_factor(effective_incline_pct / 100.0)
    treadmill_pace_s = target_gap_pace_s * adjustment

    return IntervalResult(
        name=interval.name,
        kind=interval.kind,
        distance_m=distance_m,
        duration_s=duration_s,
        target_gap_pace_s=target_gap_pace_s,
        treadmill_pace_s=treadmill_pace_s,
        pace_unit=pace_unit,
        effective_incline_pct=effective_incline_pct,
    )


def summarize_intervals(results: List[IntervalResult]) -> Tuple[float, float]:
    total_distance_m = sum(r.distance_m for r in results)
    total_duration_s = sum(r.duration_s for r in results)
    return total_distance_m, total_duration_s
