"""
Strava GAP Calculator - Streamlit App

A web interface for calculating predicted elapsed time and mile splits
for a route given target Grade Adjusted Pace (GAP) values.
"""

import streamlit as st
import pandas as pd
import io

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

st.set_page_config(
    page_title="Strava GAP Calculator",
    page_icon="🏃",
    layout="wide",
)

st.title("🏃 Strava GAP Calculator")
st.markdown(
    "Calculate predicted elapsed time and mile splits for a route "
    "based on your target Grade Adjusted Pace (GAP)."
)

# Initialize session state for GAP list
if 'gap_list' not in st.session_state:
    st.session_state.gap_list = [{'minutes': 9, 'seconds': 0}]

def add_gap():
    st.session_state.gap_list.append({'minutes': 9, 'seconds': 0})

def remove_gap(index):
    if len(st.session_state.gap_list) > 1:
        st.session_state.gap_list.pop(index)

# Sidebar for inputs
with st.sidebar:
    st.header("Upload Route")
    uploaded_file = st.file_uploader(
        "Upload a GPX file exported from Strava",
        type=["gpx"],
        help="Go to your Strava route, click the wrench icon, and select 'Export GPX'"
    )

    st.header("Target GAP(s)")

    # Display each GAP input
    for i, gap in enumerate(st.session_state.gap_list):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            st.session_state.gap_list[i]['minutes'] = st.number_input(
                f"Min" if i == 0 else f"Min ",
                min_value=4, max_value=20,
                value=gap['minutes'],
                key=f"gap_min_{i}",
                label_visibility="collapsed" if i > 0 else "visible"
            )
        with col2:
            st.session_state.gap_list[i]['seconds'] = st.number_input(
                f"Sec" if i == 0 else f"Sec ",
                min_value=0, max_value=59,
                value=gap['seconds'],
                key=f"gap_sec_{i}",
                label_visibility="collapsed" if i > 0 else "visible"
            )
        with col3:
            if i == 0:
                st.markdown("<br>", unsafe_allow_html=True)
            if len(st.session_state.gap_list) > 1:
                st.button("X", key=f"remove_{i}", on_click=remove_gap, args=(i,))

    # Add GAP button
    st.button("+ Add GAP", on_click=add_gap)

    # Show current GAPs
    gap_strings = [f"{g['minutes']}:{g['seconds']:02d}" for g in st.session_state.gap_list]
    st.markdown(f"**Comparing: {', '.join(gap_strings)}/mile**")


# Main content
if uploaded_file is not None:
    # Parse the GPX file
    try:
        # Save uploaded file temporarily and parse
        gpx_content = uploaded_file.read().decode('utf-8')

        # Write to a temporary file-like object for parsing
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', suffix='.gpx', delete=False) as f:
            f.write(gpx_content)
            temp_path = f.name

        try:
            trackpoints = parse_gpx(temp_path)
            segments = calculate_segments(trackpoints)
        finally:
            os.unlink(temp_path)

        # Calculate route stats
        total_dist = sum(s.distance for s in segments)
        total_gain = sum(s.elevation_change for s in segments if s.elevation_change > 0)
        total_loss = sum(abs(s.elevation_change) for s in segments if s.elevation_change < 0)

        # Route summary
        st.header("Route Summary")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Distance", f"{total_dist / METERS_PER_MILE:.2f} miles")
        with col2:
            st.metric("Elevation Gain", f"{total_gain * 3.28084:.0f} ft")
        with col3:
            st.metric("Elevation Loss", f"{total_loss * 3.28084:.0f} ft")

        # Calculate splits for all GAPs
        all_results = []
        for gap in st.session_state.gap_list:
            gap_str = f"{gap['minutes']}:{gap['seconds']:02d}"
            gap_secs = pace_to_seconds(gap_str)
            splits, summary = calculate_mile_splits(segments, gap_secs)
            all_results.append({
                'gap_str': gap_str,
                'gap_secs': gap_secs,
                'splits': splits,
                'summary': summary
            })

        # Results
        st.header("Predicted Results")

        # Show summary for each GAP
        cols = st.columns(len(all_results))
        for i, result in enumerate(all_results):
            with cols[i]:
                st.subheader(f"GAP: {result['gap_str']}/mile")
                st.metric("Total Time", result['summary']['total_time_formatted'])
                st.metric("Avg Actual Pace", f"{result['summary']['avg_actual_pace']}/mile")

        # Mile splits table
        st.header("Mile Splits")

        # Build combined DataFrame with all GAPs
        # Use first result for base columns (mile info is same for all)
        base_splits = all_results[0]['splits']

        rows = []
        for mile_idx, base_split in enumerate(base_splits):
            row = {
                "Mile": base_split.mile_number if base_split.distance >= METERS_PER_MILE - 10 else f"{base_split.mile_number} ({base_split.distance/METERS_PER_MILE:.2f})",
                "Grade": f"{base_split.avg_grade * 100:+.1f}%",
                "Gain (ft)": f"+{base_split.elevation_gain * 3.28084:.0f}" if base_split.elevation_gain > 0 else "-",
                "Loss (ft)": f"-{base_split.elevation_loss * 3.28084:.0f}" if base_split.elevation_loss > 0 else "-",
            }
            # Add columns for each GAP
            for result in all_results:
                gap_label = result['gap_str']
                split = result['splits'][mile_idx]
                row[f"{gap_label} Pace"] = split.actual_pace
                row[f"{gap_label} Elapsed"] = seconds_to_time(split.elapsed_time)
            rows.append(row)

        df = pd.DataFrame(rows)

        st.dataframe(df, use_container_width=True, hide_index=True)

        # Elevation profile
        st.header("Elevation Profile")

        # Build elevation data for chart
        cumulative_dist = 0
        elevation_data = []
        for i, tp in enumerate(trackpoints):
            if i > 0:
                from gap_calculator import haversine_distance
                prev = trackpoints[i-1]
                cumulative_dist += haversine_distance(prev.lat, prev.lon, tp.lat, tp.lon)
            elevation_data.append({
                "Distance (miles)": cumulative_dist / METERS_PER_MILE,
                "Elevation (ft)": tp.ele * 3.28084
            })

        elev_df = pd.DataFrame(elevation_data)
        st.line_chart(elev_df.set_index("Distance (miles)"))

        # Download results
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
    # Show instructions when no file uploaded
    st.info("👈 Upload a GPX file to get started")

    st.markdown("""
    ### How to use

    1. **Export a GPX from Strava:**
       - Go to your route on Strava web
       - Click the wrench/settings icon
       - Select "Export GPX"

    2. **Upload the GPX file** using the sidebar

    3. **Set your target GAP(s)** - add multiple to compare side by side

    4. **View your predicted splits** and total time for each GAP

    ---

    ### What is GAP?

    Grade Adjusted Pace (GAP) is Strava's metric that estimates what your pace
    would have been on flat ground, accounting for the energy cost of elevation changes.

    This calculator does the reverse: given a target GAP, it predicts your actual
    pace and elapsed time on hilly terrain.
    """)

# Footer
st.markdown("---")
st.markdown(
    "<small>Uses the Sci-DANI formula, validated against Strava with ~1.2% accuracy.</small>",
    unsafe_allow_html=True
)
