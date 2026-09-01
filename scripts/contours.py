"""Elevation contour lines for the map — a visual aid so the terrain shape around a
candidate site (the valley, the ridge the dam sits on, etc.) is visible at a glance,
instead of just a line and a label floating over a blank tile layer. Purely a rendering
concern: doesn't know anything about lakes, volume, or the search — just "given an
elevation grid, draw lines at regular height intervals", using contourpy (the same
engine matplotlib's contour plots use, without needing matplotlib itself).

See find_sites.py for where the elevation grid comes from (load_elevation_window) and
how these get attached to the output.
"""

import contourpy
import numpy as np

CONTOUR_INTERVAL_M = 50  # vertical spacing between contour lines


def generate_contours(lon_1d: np.ndarray, lat_1d: np.ndarray, elev: np.ndarray,
                       valid: np.ndarray, interval_m: float = CONTOUR_INTERVAL_M) -> list[dict]:
    """Contour lines for the given elevation grid, every interval_m of elevation.
    Returns a list of {"elevation_m": float, "coordinates": [[lon, lat], ...]} — one
    entry per line segment (a single elevation level can produce several disconnected
    segments, e.g. two separate hilltops in the same window).

    Invalid (nodata) cells are filled with the mean of the valid cells rather than left
    as nodata — contourpy needs a real number everywhere, and the mean avoids inventing
    a fake ridge or pit at the fill value the way a min/max fill would.
    """
    if not valid.any():
        return []

    fill_value = float(elev[valid].mean())
    z = np.where(valid, elev, fill_value)

    generator = contourpy.contour_generator(
        x=lon_1d, y=lat_1d, z=z, line_type=contourpy.LineType.Separate
    )

    low = interval_m * np.floor(z.min() / interval_m)
    high = interval_m * np.ceil(z.max() / interval_m)

    lines = []
    for level in np.arange(low, high + interval_m, interval_m):
        for segment in generator.lines(float(level)):
            if len(segment) < 2:
                continue
            lines.append({"elevation_m": float(level), "coordinates": segment.tolist()})
    return lines
