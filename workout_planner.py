#!/usr/bin/env python3
"""
Workout Planner CLI

Example:
python workout_planner.py \
  --base-distance marathon \
  --base-time 3:20:00 \
  --pace-unit mi \
  --treadmill-incline 5 \
  --treadmill-offset 1 \
  --interval "Warmup;warmup;2mi;effort:easy;" \
  --interval "Work;work;1mi;race:half marathon;5%" \
  --interval "Recovery;recovery;0.25mi;effort:recovery;" \
  --interval "Cooldown;cooldown;1mi;effort:easy;"
"""

import argparse
import re

from workout_utils import (
    IntervalSpec,
    compute_interval_result,
    get_equivalent_times,
    normalize_race_label,
    seconds_to_pace,
    seconds_to_time,
    summarize_intervals,
)


def parse_length(value: str):
    value = value.strip()
    if ":" in value:
        from workout_utils import time_str_to_seconds

        return "duration", time_str_to_seconds(value), "time"
    match = re.match(r"^([0-9]*\.?[0-9]+)\s*(mi|km|m)$", value.lower())
    if not match:
        raise ValueError(f"Invalid length format: {value}. Use 2mi, 1.5km, 400m, or 10:00")
    number = float(match.group(1))
    unit = match.group(2)
    return "distance", number, unit


def parse_pace(value: str):
    value = value.strip()
    if value.lower().startswith("race:"):
        return "race", value.split(":", 1)[1].strip()
    if value.lower().startswith("effort:"):
        return "effort", value.split(":", 1)[1].strip()
    return "manual", value


def parse_incline(value: str):
    value = value.strip()
    if not value:
        return None
    if value.endswith("%"):
        return float(value[:-1])
    return float(value)


def parse_interval(raw: str) -> IntervalSpec:
    parts = [p.strip() for p in raw.split(";")]
    if len(parts) < 4:
        raise ValueError("Interval must have at least 4 fields: name;kind;length;pace;[incline]")
    name, kind, length_raw, pace_raw = parts[:4]
    incline_raw = parts[4] if len(parts) > 4 else ""
    length_type, length_value, length_unit = parse_length(length_raw)
    pace_source, pace_value = parse_pace(pace_raw)
    incline_pct = parse_incline(incline_raw)
    return IntervalSpec(
        name=name,
        kind=kind,
        length_type=length_type,
        length_value=length_value,
        length_unit=length_unit,
        pace_source=pace_source,
        pace_value=pace_value,
        incline_pct=incline_pct,
    )


def main():
    parser = argparse.ArgumentParser(description="Plan treadmill/interval workouts from race-equivalent paces.")
    parser.add_argument("--base-distance", required=True, help="Base race distance (e.g., marathon, 10k)")
    parser.add_argument("--base-time", required=True, help="Base race time (h:mm:ss or mm:ss)")
    parser.add_argument("--pace-unit", choices=["mi", "km"], default="mi", help="Pace unit for outputs")
    parser.add_argument("--treadmill-incline", type=float, default=0.0, help="Workout treadmill incline percent")
    parser.add_argument("--treadmill-offset", type=float, default=1.0, help="Treadmill offset percent")
    parser.add_argument(
        "--interval",
        action="append",
        required=True,
        help="Interval spec: name;kind;length;pace;[incline]. Length: 2mi/1.5km/400m or 10:00. "
             "Pace: mm:ss or race:<label> or effort:<label>. Incline: 5%",
    )

    args = parser.parse_args()

    from workout_utils import time_str_to_seconds

    base_distance = normalize_race_label(args.base_distance)
    base_time_s = time_str_to_seconds(args.base_time)

    intervals = [parse_interval(raw) for raw in args.interval]
    results = [
        compute_interval_result(
            interval,
            base_distance_label=base_distance,
            base_time_s=base_time_s,
            pace_unit=args.pace_unit,
            workout_incline_pct=args.treadmill_incline,
            treadmill_offset_pct=args.treadmill_offset,
        )
        for interval in intervals
    ]

    print("\nRace Equivalents (Riegel):")
    for label, time_s in get_equivalent_times(base_distance, base_time_s).items():
        print(f"  {label.title():<14} {seconds_to_time(time_s)}")

    print("\nIntervals:")
    header = f"{'Name':<12} {'Type':<10} {'Dist':<10} {'Time':<10} {'GAP Pace':<10} {'TM Pace':<10} {'Eff%':<6}"
    print(header)
    print("-" * len(header))

    for result in results:
        distance_label = f"{result.distance_m / (1609.344 if result.pace_unit == 'mi' else 1000.0):.2f}{result.pace_unit}"
        print(
            f"{result.name:<12} {result.kind:<10} {distance_label:<10} {seconds_to_time(result.duration_s):<10} "
            f"{seconds_to_pace(result.target_gap_pace_s):<10} {seconds_to_pace(result.treadmill_pace_s):<10} "
            f"{result.effective_incline_pct:+.1f}%"
        )

    total_distance_m, total_duration_s = summarize_intervals(results)
    total_dist = total_distance_m / (1609.344 if args.pace_unit == "mi" else 1000.0)
    print("\nTotals:")
    print(f"  Distance: {total_dist:.2f}{args.pace_unit}")
    print(f"  Time: {seconds_to_time(total_duration_s)}")


if __name__ == "__main__":
    main()
