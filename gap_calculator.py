#!/usr/bin/env python3
"""
Strava GAP Calculator

Calculate predicted elapsed time and mile splits for a route
given target Grade Adjusted Pace (GAP) values.

Usage:
    python gap_calculator.py route.gpx --gap 8:00 9:00 10:00
"""

import argparse
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Tuple


# Earth's radius in meters
EARTH_RADIUS_M = 6371000

# Meters per mile
METERS_PER_MILE = 1609.344


@dataclass
class TrackPoint:
    """A single GPS trackpoint with latitude, longitude, and elevation."""
    lat: float
    lon: float
    ele: float  # elevation in meters


@dataclass
class Segment:
    """A segment between two trackpoints with calculated metrics."""
    distance: float  # meters
    elevation_change: float  # meters
    grade: float  # decimal (0.1 = 10%)


@dataclass
class MileSplit:
    """Calculated metrics for a single mile."""
    mile_number: int
    distance: float  # actual distance in meters (should be ~1609)
    elevation_gain: float  # meters
    elevation_loss: float  # meters
    avg_grade: float  # decimal
    gap: str  # target GAP (mm:ss format)
    actual_pace: str  # predicted actual pace (mm:ss format)
    actual_pace_seconds: float
    elapsed_time: float  # cumulative seconds


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on Earth.

    Args:
        lat1, lon1: First point coordinates in degrees
        lat2, lon2: Second point coordinates in degrees

    Returns:
        Distance in meters
    """
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def parse_gpx(filepath: str) -> List[TrackPoint]:
    """
    Parse a GPX file and extract trackpoints.

    Args:
        filepath: Path to GPX file

    Returns:
        List of TrackPoint objects
    """
    tree = ET.parse(filepath)
    root = tree.getroot()

    # Handle GPX namespace
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}

    trackpoints = []

    # Find all trackpoints
    for trkpt in root.findall('.//gpx:trkpt', ns):
        lat = float(trkpt.get('lat'))
        lon = float(trkpt.get('lon'))

        ele_elem = trkpt.find('gpx:ele', ns)
        ele = float(ele_elem.text) if ele_elem is not None else 0.0

        trackpoints.append(TrackPoint(lat=lat, lon=lon, ele=ele))

    return trackpoints


def calculate_segments(trackpoints: List[TrackPoint]) -> List[Segment]:
    """
    Calculate segments between consecutive trackpoints.

    Args:
        trackpoints: List of TrackPoint objects

    Returns:
        List of Segment objects with distance, elevation change, and grade
    """
    segments = []

    for i in range(1, len(trackpoints)):
        prev = trackpoints[i - 1]
        curr = trackpoints[i]

        # Horizontal distance
        horiz_dist = haversine_distance(prev.lat, prev.lon, curr.lat, curr.lon)

        # Elevation change
        ele_change = curr.ele - prev.ele

        # Total distance (accounting for slope)
        total_dist = math.sqrt(horiz_dist ** 2 + ele_change ** 2)

        # Grade (rise over run)
        if horiz_dist > 0:
            grade = ele_change / horiz_dist
        else:
            grade = 0.0

        # Clamp grade to reasonable range (-45% to +45%)
        grade = max(-0.45, min(0.45, grade))

        segments.append(Segment(
            distance=total_dist,
            elevation_change=ele_change,
            grade=grade
        ))

    return segments


def gap_adjustment_factor(grade_decimal: float) -> float:
    """
    Calculate the GAP adjustment factor for a given grade.

    Uses the Sci-DANI formula reverse-engineered from Strava data:
    a(g) = 1 + 0.02869556*g + 0.001520768*g²
    where g is the grade as a percentage.

    Validated against 92 runs with mean error of +1.24% vs Strava.

    Args:
        grade_decimal: Grade as decimal (0.1 = 10%)

    Returns:
        Adjustment factor (multiply GAP by this to get actual pace)
    """
    g = grade_decimal * 100
    factor = 1.0 + 0.02869556 * g + 0.001520768 * g * g
    return max(0.5, factor)


def pace_to_seconds(pace_str: str) -> float:
    """
    Convert pace string (mm:ss) to seconds per mile.

    Args:
        pace_str: Pace in "mm:ss" format

    Returns:
        Seconds per mile
    """
    parts = pace_str.split(':')
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    else:
        raise ValueError(f"Invalid pace format: {pace_str}. Expected mm:ss")


def seconds_to_pace(seconds: float) -> str:
    """
    Convert seconds per mile to pace string (mm:ss).

    Args:
        seconds: Seconds per mile

    Returns:
        Pace in "mm:ss" format
    """
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def seconds_to_time(seconds: float) -> str:
    """
    Convert total seconds to time string (h:mm:ss or mm:ss).

    Args:
        seconds: Total seconds

    Returns:
        Time in "h:mm:ss" or "mm:ss" format
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def calculate_mile_splits(
    segments: List[Segment],
    gap_seconds: float
) -> Tuple[List[MileSplit], dict]:
    """
    Calculate mile-by-mile splits for a given target GAP.

    The key insight is that GAP adjustment is nonlinear, so we must calculate
    the adjustment factor for each segment and then distance-weight those
    factors, NOT average the grades and then calculate adjustment.

    Args:
        segments: List of route segments
        gap_seconds: Target GAP in seconds per mile

    Returns:
        Tuple of (list of MileSplit objects, summary dict)
    """
    mile_splits = []

    current_mile = 1
    mile_distance = 0.0
    mile_elevation_gain = 0.0
    mile_elevation_loss = 0.0
    mile_weighted_adjustment = 0.0  # distance-weighted adjustment factors
    mile_weighted_grade = 0.0  # for display purposes only
    total_elapsed = 0.0

    total_distance = sum(s.distance for s in segments)
    total_elevation_gain = sum(s.elevation_change for s in segments if s.elevation_change > 0)

    for segment in segments:
        remaining_segment = segment.distance
        segment_adjustment = gap_adjustment_factor(segment.grade)

        while remaining_segment > 0:
            # How much distance until we complete this mile?
            distance_to_mile = METERS_PER_MILE - mile_distance

            # Take what we can from this segment
            distance_used = min(remaining_segment, distance_to_mile)
            fraction = distance_used / segment.distance if segment.distance > 0 else 0

            # Accumulate metrics
            mile_distance += distance_used
            ele_change = segment.elevation_change * fraction
            if ele_change > 0:
                mile_elevation_gain += ele_change
            else:
                mile_elevation_loss += abs(ele_change)

            # Weight the adjustment factor by distance (this is the fix!)
            mile_weighted_adjustment += segment_adjustment * distance_used
            mile_weighted_grade += segment.grade * distance_used  # for display

            remaining_segment -= distance_used

            # Check if mile is complete
            if mile_distance >= METERS_PER_MILE - 0.1:  # small tolerance
                # Calculate average adjustment factor for this mile
                avg_adjustment = mile_weighted_adjustment / mile_distance if mile_distance > 0 else 1.0
                avg_grade = mile_weighted_grade / mile_distance if mile_distance > 0 else 0

                # Calculate actual pace using the averaged adjustment
                actual_pace_seconds = gap_seconds * avg_adjustment

                # Calculate time for this mile
                mile_time = actual_pace_seconds * (mile_distance / METERS_PER_MILE)
                total_elapsed += mile_time

                mile_splits.append(MileSplit(
                    mile_number=current_mile,
                    distance=mile_distance,
                    elevation_gain=mile_elevation_gain,
                    elevation_loss=mile_elevation_loss,
                    avg_grade=avg_grade,
                    gap=seconds_to_pace(gap_seconds),
                    actual_pace=seconds_to_pace(actual_pace_seconds),
                    actual_pace_seconds=actual_pace_seconds,
                    elapsed_time=total_elapsed
                ))

                # Reset for next mile
                current_mile += 1
                mile_distance = 0.0
                mile_elevation_gain = 0.0
                mile_elevation_loss = 0.0
                mile_weighted_adjustment = 0.0
                mile_weighted_grade = 0.0

    # Handle partial final mile
    if mile_distance > 100:  # Only if meaningful distance remaining
        avg_adjustment = mile_weighted_adjustment / mile_distance if mile_distance > 0 else 1.0
        avg_grade = mile_weighted_grade / mile_distance if mile_distance > 0 else 0
        actual_pace_seconds = gap_seconds * avg_adjustment
        mile_time = actual_pace_seconds * (mile_distance / METERS_PER_MILE)
        total_elapsed += mile_time

        mile_splits.append(MileSplit(
            mile_number=current_mile,
            distance=mile_distance,
            elevation_gain=mile_elevation_gain,
            elevation_loss=mile_elevation_loss,
            avg_grade=avg_grade,
            gap=seconds_to_pace(gap_seconds),
            actual_pace=seconds_to_pace(actual_pace_seconds),
            actual_pace_seconds=actual_pace_seconds,
            elapsed_time=total_elapsed
        ))

    # Calculate summary stats
    avg_actual_pace = total_elapsed / (total_distance / METERS_PER_MILE)

    summary = {
        'total_distance_miles': total_distance / METERS_PER_MILE,
        'total_elevation_gain_ft': total_elevation_gain * 3.28084,
        'total_time_seconds': total_elapsed,
        'total_time_formatted': seconds_to_time(total_elapsed),
        'avg_actual_pace': seconds_to_pace(avg_actual_pace),
        'target_gap': seconds_to_pace(gap_seconds)
    }

    return mile_splits, summary


def print_results(splits: List[MileSplit], summary: dict) -> None:
    """Print formatted results to console."""
    print("\n" + "=" * 70)
    print(f"TARGET GAP: {summary['target_gap']}/mile")
    print("=" * 70)
    print(f"Total Distance: {summary['total_distance_miles']:.2f} miles")
    print(f"Total Elevation Gain: {summary['total_elevation_gain_ft']:.0f} ft")
    print(f"Predicted Total Time: {summary['total_time_formatted']}")
    print(f"Average Actual Pace: {summary['avg_actual_pace']}/mile")
    print()

    # Print mile splits table
    print(f"{'Mile':<6} {'Grade':<8} {'Gain':<8} {'Loss':<8} {'GAP':<8} {'Actual':<8} {'Elapsed':<10}")
    print("-" * 70)

    for split in splits:
        grade_pct = f"{split.avg_grade * 100:+.1f}%"
        gain = f"+{split.elevation_gain * 3.28084:.0f}ft" if split.elevation_gain > 0 else "-"
        loss = f"-{split.elevation_loss * 3.28084:.0f}ft" if split.elevation_loss > 0 else "-"

        # Mark partial miles
        mile_label = str(split.mile_number)
        if split.distance < METERS_PER_MILE - 10:
            mile_label += f" ({split.distance / METERS_PER_MILE:.2f})"

        print(f"{mile_label:<6} {grade_pct:<8} {gain:<8} {loss:<8} {split.gap:<8} {split.actual_pace:<8} {seconds_to_time(split.elapsed_time):<10}")


def main():
    parser = argparse.ArgumentParser(
        description="Calculate predicted time and splits for a route at target GAP values."
    )
    parser.add_argument(
        "gpx_file",
        help="Path to GPX file exported from Strava"
    )
    parser.add_argument(
        "--gap", "-g",
        nargs="+",
        required=True,
        help="Target GAP values in mm:ss format (e.g., 8:00 9:00 10:00)"
    )

    args = parser.parse_args()

    # Parse GPX file
    print(f"Loading route from: {args.gpx_file}")
    trackpoints = parse_gpx(args.gpx_file)
    print(f"Found {len(trackpoints)} trackpoints")

    # Calculate segments
    segments = calculate_segments(trackpoints)
    total_dist = sum(s.distance for s in segments)
    total_gain = sum(s.elevation_change for s in segments if s.elevation_change > 0)
    print(f"Route: {total_dist / METERS_PER_MILE:.2f} miles, {total_gain * 3.28084:.0f} ft gain")

    # Process each GAP target
    for gap_str in args.gap:
        try:
            gap_seconds = pace_to_seconds(gap_str)
            splits, summary = calculate_mile_splits(segments, gap_seconds)
            print_results(splits, summary)
        except ValueError as e:
            print(f"Error processing GAP {gap_str}: {e}")


if __name__ == "__main__":
    main()
