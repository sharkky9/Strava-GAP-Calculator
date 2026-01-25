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

# Sidebar for inputs
with st.sidebar:
    st.header("Upload Route")
    uploaded_file = st.file_uploader(
        "Upload a GPX file exported from Strava",
        type=["gpx"],
        help="Go to your Strava route, click the wrench icon, and select 'Export GPX'"
    )

    st.header("Target GAP")

    col1, col2 = st.columns(2)
    with col1:
        gap_minutes = st.number_input("Minutes", min_value=4, max_value=20, value=9)
    with col2:
        gap_seconds = st.number_input("Seconds", min_value=0, max_value=59, value=0)

    gap_str = f"{gap_minutes}:{gap_seconds:02d}"
    st.markdown(f"**Target GAP: {gap_str}/mile**")

    # Option for multiple GAPs
    st.markdown("---")
    compare_mode = st.checkbox("Compare multiple GAPs")

    if compare_mode:
        col1, col2 = st.columns(2)
        with col1:
            gap2_minutes = st.number_input("Minutes ", min_value=4, max_value=20, value=9, key="gap2_min")
        with col2:
            gap2_seconds = st.number_input("Seconds ", min_value=0, max_value=59, value=30, key="gap2_sec")
        gap2_str = f"{gap2_minutes}:{gap2_seconds:02d}"


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

        # Calculate splits for primary GAP
        gap_secs = pace_to_seconds(gap_str)
        splits, summary = calculate_mile_splits(segments, gap_secs)

        # Results
        st.header("Predicted Results")

        if compare_mode:
            # Compare two GAPs side by side
            gap2_secs = pace_to_seconds(gap2_str)
            splits2, summary2 = calculate_mile_splits(segments, gap2_secs)

            col1, col2 = st.columns(2)

            with col1:
                st.subheader(f"GAP: {gap_str}/mile")
                st.metric("Total Time", summary['total_time_formatted'])
                st.metric("Avg Actual Pace", f"{summary['avg_actual_pace']}/mile")

            with col2:
                st.subheader(f"GAP: {gap2_str}/mile")
                st.metric("Total Time", summary2['total_time_formatted'])
                st.metric("Avg Actual Pace", f"{summary2['avg_actual_pace']}/mile")
        else:
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Predicted Total Time", summary['total_time_formatted'])
            with col2:
                st.metric("Average Actual Pace", f"{summary['avg_actual_pace']}/mile")

        # Mile splits table
        st.header("Mile Splits")

        # Convert splits to DataFrame
        df = pd.DataFrame([
            {
                "Mile": s.mile_number if s.distance >= METERS_PER_MILE - 10 else f"{s.mile_number} ({s.distance/METERS_PER_MILE:.2f})",
                "Grade": f"{s.avg_grade * 100:+.1f}%",
                "Gain (ft)": f"+{s.elevation_gain * 3.28084:.0f}" if s.elevation_gain > 0 else "-",
                "Loss (ft)": f"-{s.elevation_loss * 3.28084:.0f}" if s.elevation_loss > 0 else "-",
                "GAP": s.gap,
                "Actual Pace": s.actual_pace,
                "Elapsed": seconds_to_time(s.elapsed_time),
            }
            for s in splits
        ])

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

    3. **Set your target GAP** (Grade Adjusted Pace)

    4. **View your predicted splits** and total time

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
