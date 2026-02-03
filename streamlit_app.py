"""
Strava GAP Calculator - Streamlit App

A web interface for calculating predicted elapsed time and mile splits
for a route given target Grade Adjusted Pace (GAP) values.
"""

import streamlit as st
import pandas as pd

# Import core logic from gap_calculator
from gap_calculator import (
    parse_gpx,
    calculate_segments,
    calculate_mile_splits,
    pace_to_seconds,
    seconds_to_pace,
    seconds_to_time,
    METERS_PER_MILE,
)

from workout_utils import (
    IntervalSpec,
    compute_interval_result,
    get_equivalent_times,
    summarize_intervals,
    meters_to_distance,
    normalize_race_label,
    seconds_to_pace as workout_seconds_to_pace,
    seconds_to_time as workout_seconds_to_time,
    time_str_to_seconds,
    RACE_DISTANCES_M,
    EFFORT_MULTIPLIERS,
)

st.set_page_config(
    page_title="Strava GAP Calculator",
    page_icon="🏃",
    layout="wide",
)

st.title("🏃 Strava GAP Calculator")

# Initialize session state for GAP list
if "gap_list" not in st.session_state:
    st.session_state.gap_list = [{"minutes": 9, "seconds": 0}]

# Initialize session state for workout intervals
if "workout_intervals" not in st.session_state:
    st.session_state.workout_intervals = [
        {
            "name": "Warmup",
            "kind": "warmup",
            "length_type": "distance",
            "length_value": 2.0,
            "length_unit": "mi",
            "duration_minutes": 10,
            "duration_seconds": 0,
            "pace_source": "effort",
            "pace_value": "easy",
            "pace_minutes": 9,
            "pace_seconds": 0,
            "incline_override": False,
            "incline_pct": 0.0,
        }
    ]


def add_gap():
    st.session_state.gap_list.append({"minutes": 9, "seconds": 0})


def remove_gap(index):
    if len(st.session_state.gap_list) > 1:
        st.session_state.gap_list.pop(index)


def add_interval():
    st.session_state.workout_intervals.append(
        {
            "name": f"Interval {len(st.session_state.workout_intervals) + 1}",
            "kind": "work",
            "length_type": "distance",
            "length_value": 1.0,
            "length_unit": "mi",
            "duration_minutes": 5,
            "duration_seconds": 0,
            "pace_source": "race",
            "pace_value": "half marathon",
            "pace_minutes": 7,
            "pace_seconds": 30,
            "incline_override": False,
            "incline_pct": 0.0,
        }
    )


def remove_interval(index):
    if len(st.session_state.workout_intervals) > 1:
        st.session_state.workout_intervals.pop(index)


route_tab, workout_tab = st.tabs(["Route GAP Calculator", "Workout Planner"])

with route_tab:
    st.markdown(
        "Calculate predicted elapsed time and mile splits for a route "
        "based on your target Grade Adjusted Pace (GAP)."
    )

    with st.sidebar:
        st.header("Upload Route")
        uploaded_file = st.file_uploader(
            "Upload a GPX file exported from Strava",
            type=["gpx"],
            help="Go to your Strava route, click the wrench icon, and select 'Export GPX'",
        )

        st.header("Target GAP(s)")

        # Display each GAP input
        for i, gap in enumerate(st.session_state.gap_list):
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.session_state.gap_list[i]["minutes"] = st.number_input(
                    "Min" if i == 0 else "Min ",
                    min_value=4,
                    max_value=20,
                    value=gap["minutes"],
                    key=f"gap_min_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col2:
                st.session_state.gap_list[i]["seconds"] = st.number_input(
                    "Sec" if i == 0 else "Sec ",
                    min_value=0,
                    max_value=59,
                    value=gap["seconds"],
                    key=f"gap_sec_{i}",
                    label_visibility="collapsed" if i > 0 else "visible",
                )
            with col3:
                if i == 0:
                    st.markdown("<br>", unsafe_allow_html=True)
                if len(st.session_state.gap_list) > 1:
                    st.button("X", key=f"remove_{i}", on_click=remove_gap, args=(i,))

        st.button("+ Add GAP", on_click=add_gap)

        gap_strings = [f"{g['minutes']}:{g['seconds']:02d}" for g in st.session_state.gap_list]
        st.markdown(f"**Comparing: {', '.join(gap_strings)}/mile**")

    if uploaded_file is not None:
        try:
            gpx_content = uploaded_file.read().decode("utf-8")

            import tempfile
            import os

            with tempfile.NamedTemporaryFile(mode="w", suffix=".gpx", delete=False) as f:
                f.write(gpx_content)
                temp_path = f.name

            try:
                trackpoints = parse_gpx(temp_path)
                segments = calculate_segments(trackpoints)
            finally:
                os.unlink(temp_path)

            total_dist = sum(s.distance for s in segments)
            total_gain = sum(s.elevation_change for s in segments if s.elevation_change > 0)
            total_loss = sum(abs(s.elevation_change) for s in segments if s.elevation_change < 0)

            st.header("Route Summary")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Distance", f"{total_dist / METERS_PER_MILE:.2f} miles")
            with col2:
                st.metric("Elevation Gain", f"{total_gain * 3.28084:.0f} ft")
            with col3:
                st.metric("Elevation Loss", f"{total_loss * 3.28084:.0f} ft")

            all_results = []
            for gap in st.session_state.gap_list:
                gap_str = f"{gap['minutes']}:{gap['seconds']:02d}"
                gap_secs = pace_to_seconds(gap_str)
                splits, summary = calculate_mile_splits(segments, gap_secs)
                all_results.append({
                    "gap_str": gap_str,
                    "gap_secs": gap_secs,
                    "splits": splits,
                    "summary": summary,
                })

            st.header("Predicted Results")
            cols = st.columns(len(all_results))
            for i, result in enumerate(all_results):
                with cols[i]:
                    st.subheader(f"GAP: {result['gap_str']}/mile")
                    st.metric("Total Time", result["summary"]["total_time_formatted"])
                    st.metric("Avg Actual Pace", f"{result['summary']['avg_actual_pace']}/mile")

            st.header("Mile Splits")
            base_splits = all_results[0]["splits"]
            data = []
            for mile_idx, base_split in enumerate(base_splits):
                row = [
                    base_split.mile_number
                    if base_split.distance >= METERS_PER_MILE - 10
                    else f"{base_split.mile_number} ({base_split.distance/METERS_PER_MILE:.2f})",
                    f"{base_split.avg_grade * 100:+.1f}%",
                    f"+{base_split.elevation_gain * 3.28084:.0f}" if base_split.elevation_gain > 0 else "-",
                    f"-{base_split.elevation_loss * 3.28084:.0f}" if base_split.elevation_loss > 0 else "-",
                ]
                for result in all_results:
                    split = result["splits"][mile_idx]
                    row.append(split.actual_pace)
                    row.append(seconds_to_time(split.elapsed_time))
                data.append(row)

            base_columns = [
                ("", "Mile"),
                ("", "Grade"),
                ("", "Gain (ft)"),
                ("", "Loss (ft)"),
            ]
            gap_columns = []
            for result in all_results:
                gap_label = f"{result['gap_str']} GAP"
                gap_columns.append((gap_label, "Pace"))
                gap_columns.append((gap_label, "Elapsed"))

            columns = pd.MultiIndex.from_tuples(base_columns + gap_columns)
            df = pd.DataFrame(data, columns=columns)

            st.dataframe(df, use_container_width=True, hide_index=True)

            st.header("Elevation Profile")
            cumulative_dist = 0
            elevation_data = []
            for i, tp in enumerate(trackpoints):
                if i > 0:
                    from gap_calculator import haversine_distance

                    prev = trackpoints[i - 1]
                    cumulative_dist += haversine_distance(prev.lat, prev.lon, tp.lat, tp.lon)
                elevation_data.append({
                    "Distance (miles)": cumulative_dist / METERS_PER_MILE,
                    "Elevation (ft)": tp.ele * 3.28084,
                })

            elev_df = pd.DataFrame(elevation_data)
            st.line_chart(elev_df.set_index("Distance (miles)"))

            st.header("Export")
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download splits as CSV",
                data=csv,
                file_name="gap_splits.csv",
                mime="text/csv",
            )

        except Exception as e:
            st.error(f"Error processing GPX file: {str(e)}")
    else:
        st.info("👈 Upload a GPX file to get started")

        st.markdown(
            """
            ### How to use

            1. **Export a GPX from Strava:**
               - Go to your route on Strava web
               - Click the wrench/settings icon
               - Select "Export GPX"

            2. **Upload the GPX file** using the sidebar

            3. **Set your target GAP(s)** - add multiple to compare side by side

            4. **View your predicted splits** and total time for each GAP
            """
        )

with workout_tab:
    st.markdown(
        "Plan interval workouts using race-equivalent paces and treadmill incline adjustments."
    )

    st.subheader("Race Equivalent Input")
    race_labels = list(RACE_DISTANCES_M.keys())
    base_distance_label = st.selectbox("Base race distance", race_labels, index=race_labels.index("marathon"))
    base_time_str = st.text_input("Base race time (h:mm:ss or mm:ss)", value="3:20:00")

    pace_unit = st.radio("Pace unit", ["mi", "km"], horizontal=True)

    st.subheader("Treadmill Settings")
    col1, col2 = st.columns(2)
    with col1:
        workout_incline_pct = st.number_input("Workout incline (%)", value=0.0, step=0.5)
    with col2:
        treadmill_offset_pct = st.number_input("Treadmill offset (%)", value=1.0, step=0.5)

    st.subheader("Intervals")
    for idx, interval in enumerate(st.session_state.workout_intervals):
        st.markdown("---")
        row1 = st.columns([2, 1.5, 2, 2, 1])
        with row1[0]:
            interval["name"] = st.text_input("Name", value=interval["name"], key=f"name_{idx}")
        with row1[1]:
            interval["kind"] = st.selectbox(
                "Type",
                ["warmup", "work", "recovery", "cooldown"],
                index=["warmup", "work", "recovery", "cooldown"].index(interval["kind"]),
                key=f"kind_{idx}",
            )
        with row1[2]:
            interval["length_type"] = st.selectbox(
                "Length",
                ["distance", "duration"],
                index=["distance", "duration"].index(interval["length_type"]),
                key=f"length_type_{idx}",
            )
        with row1[3]:
            if interval["length_type"] == "distance":
                interval["length_value"] = st.number_input(
                    "Value",
                    value=float(interval["length_value"]),
                    min_value=0.01,
                    step=0.05,
                    key=f"length_val_{idx}",
                )
                unit_options = ["mi", "km", "m"]
                current_unit = interval["length_unit"] if interval["length_unit"] in unit_options else "mi"
                interval["length_unit"] = st.selectbox(
                    "Unit",
                    unit_options,
                    index=unit_options.index(current_unit),
                    key=f"length_unit_{idx}",
                )
            else:
                interval["duration_minutes"] = st.number_input(
                    "Minutes",
                    value=int(interval["duration_minutes"]),
                    min_value=0,
                    max_value=240,
                    step=1,
                    key=f"dur_min_{idx}",
                )
                interval["duration_seconds"] = st.number_input(
                    "Seconds",
                    value=int(interval["duration_seconds"]),
                    min_value=0,
                    max_value=59,
                    step=5,
                    key=f"dur_sec_{idx}",
                )
        with row1[4]:
            if len(st.session_state.workout_intervals) > 1:
                st.button("Remove", key=f"remove_interval_{idx}", on_click=remove_interval, args=(idx,))

        row2 = st.columns([2, 2, 2, 2])
        with row2[0]:
            interval["pace_source"] = st.selectbox(
                "Pace Source",
                ["manual", "race", "effort"],
                index=["manual", "race", "effort"].index(interval["pace_source"]),
                key=f"pace_source_{idx}",
            )
        with row2[1]:
            if interval["pace_source"] == "manual":
                interval["pace_minutes"] = st.number_input(
                    "Pace min",
                    value=int(interval["pace_minutes"]),
                    min_value=3,
                    max_value=20,
                    step=1,
                    key=f"pace_min_{idx}",
                )
                interval["pace_seconds"] = st.number_input(
                    "Pace sec",
                    value=int(interval["pace_seconds"]),
                    min_value=0,
                    max_value=59,
                    step=1,
                    key=f"pace_sec_{idx}",
                )
            elif interval["pace_source"] == "race":
                interval["pace_value"] = st.selectbox(
                    "Race pace",
                    race_labels,
                    index=race_labels.index(interval["pace_value"]) if interval["pace_value"] in race_labels else 0,
                    key=f"pace_race_{idx}",
                )
            else:
                effort_labels = list(EFFORT_MULTIPLIERS.keys())
                interval["pace_value"] = st.selectbox(
                    "Effort",
                    effort_labels,
                    index=effort_labels.index(interval["pace_value"]) if interval["pace_value"] in effort_labels else 0,
                    key=f"pace_effort_{idx}",
                )
        with row2[2]:
            interval["incline_override"] = st.checkbox(
                "Override incline",
                value=interval["incline_override"],
                key=f"incline_override_{idx}",
            )
        with row2[3]:
            if interval["incline_override"]:
                interval["incline_pct"] = st.number_input(
                    "Incline (%)",
                    value=float(interval["incline_pct"]),
                    step=0.5,
                    key=f"incline_pct_{idx}",
                )

    st.button("+ Add Interval", on_click=add_interval)

    st.subheader("Outputs")

    try:
        base_distance_norm = normalize_race_label(base_distance_label)
        base_time_s = time_str_to_seconds(base_time_str)

        equivalents = get_equivalent_times(base_distance_norm, base_time_s)
        eq_rows = []
        for label, time_s in equivalents.items():
            pace_s = time_s / (RACE_DISTANCES_M[label] / (METERS_PER_MILE if pace_unit == "mi" else 1000.0))
            eq_rows.append({
                "Race": label.title(),
                "Time": workout_seconds_to_time(time_s),
                f"Pace ({pace_unit})": workout_seconds_to_pace(pace_s),
            })
        eq_df = pd.DataFrame(eq_rows)
        st.dataframe(eq_df, use_container_width=True, hide_index=True)

        interval_results = []
        for interval in st.session_state.workout_intervals:
            if interval["pace_source"] == "manual":
                pace_str = f"{int(interval['pace_minutes'])}:{int(interval['pace_seconds']):02d}"
                interval["pace_value"] = pace_str
            if interval["length_type"] == "duration":
                duration_s = int(interval["duration_minutes"]) * 60 + int(interval["duration_seconds"])
                interval["length_value"] = duration_s
                interval["length_unit"] = "time"

            spec = IntervalSpec(
                name=interval["name"],
                kind=interval["kind"],
                length_type=interval["length_type"],
                length_value=float(interval["length_value"]),
                length_unit=interval["length_unit"],
                pace_source=interval["pace_source"],
                pace_value=interval["pace_value"],
                incline_pct=interval["incline_pct"] if interval["incline_override"] else None,
            )

            interval_results.append(
                compute_interval_result(
                    spec,
                    base_distance_label=base_distance_norm,
                    base_time_s=base_time_s,
                    pace_unit=pace_unit,
                    workout_incline_pct=workout_incline_pct,
                    treadmill_offset_pct=treadmill_offset_pct,
                )
            )

        output_rows = []
        for result in interval_results:
            dist = meters_to_distance(result.distance_m, pace_unit)
            output_rows.append({
                "Name": result.name,
                "Type": result.kind,
                f"Distance ({pace_unit})": f"{dist:.2f}",
                "Duration": workout_seconds_to_time(result.duration_s),
                "Target GAP": workout_seconds_to_pace(result.target_gap_pace_s),
                "Treadmill Pace": workout_seconds_to_pace(result.treadmill_pace_s),
                "Eff Incline": f"{result.effective_incline_pct:+.1f}%",
            })

        output_df = pd.DataFrame(output_rows)
        st.dataframe(output_df, use_container_width=True, hide_index=True)

        total_distance_m, total_duration_s = summarize_intervals(interval_results)
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Distance", f"{meters_to_distance(total_distance_m, pace_unit):.2f} {pace_unit}")
        with col2:
            st.metric("Total Time", workout_seconds_to_time(total_duration_s))

    except Exception as exc:
        st.error(f"Workout planner error: {exc}")
