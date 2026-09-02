"""A rough concrete-volume estimate for the dam wall itself — separate from how much
WATER the reservoir behind it holds (see volumes.py) or where exactly it sits
(find_sites.py's dam_line_endpoints). Deliberately a crude order-of-magnitude figure:
real dam volume depends heavily on dam type (gravity / arch / embankment), geology, and
detailed engineering design that can't be inferred from a DEM alone.
"""

# A concrete GRAVITY dam's base width is commonly sized to roughly 0.7-0.8x its height,
# for stability against sliding and overturning under the reservoir's water pressure —
# a standard textbook rule of thumb, not derived from a specific real project (unlike
# the physics in volumes.py, which is checked against real plants). Gravity is a
# deliberately generic default, not a claim about what type of dam a site needs:
#   - An ARCH dam (like the real Tarnița itself, 97m tall on a 237m crest) needs far
#     less concrete for the same height — arch action carries much of the load into the
#     valley walls instead of the dam's own mass. This estimate is likely a substantial
#     OVERESTIMATE for a site where an arch dam would be viable (a narrow, strong-walled
#     gorge — exactly what our "engineered" search tends to find).
#   - An EMBANKMENT (earthfill/rockfill) dam — more typical for remote sites where
#     hauling in concrete is impractical — uses compacted earth/rock as the bulk
#     material, not concrete, so this estimate doesn't apply to it at all.
# Treat this as "if this were built as a plain concrete gravity dam", not a real design
# volume for whatever type actually gets chosen.
GRAVITY_DAM_BASE_TO_HEIGHT_RATIO = 0.75


def estimate_concrete_volume_m3(dam_height_m: float, dam_length_m: float) -> float:
    """Triangular gravity-dam cross-section (base_width = ratio * height), extruded
    along the dam's length. Both dam_height_m and dam_length_m should be >= 0; returns
    0 for a non-positive height or length (no dam, nothing to estimate)."""
    if dam_height_m <= 0 or dam_length_m <= 0:
        return 0.0
    base_width_m = GRAVITY_DAM_BASE_TO_HEIGHT_RATIO * dam_height_m
    cross_section_area_m2 = 0.5 * base_width_m * dam_height_m
    return cross_section_area_m2 * dam_length_m
