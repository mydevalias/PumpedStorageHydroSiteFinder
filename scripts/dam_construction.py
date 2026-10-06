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
#
# Valley profile: in natural topography, a dam spans a valley where height tapers from
# maximum H at the riverbed/thalweg to 0 at both abutments. A uniform rectangular extrusion
# overestimates concrete volume by ~2-3x (for a pure V-notch valley, the integral of h(x)^2
# is exactly 1/3 of the prismatic volume; for a typical trapezoidal gorge with a flat floor,
# the shape factor is ~0.5). We use 0.5 as a realistic trapezoidal valley profile factor.
GRAVITY_DAM_BASE_TO_HEIGHT_RATIO = 0.75
VALLEY_SHAPE_FACTOR = 0.5


def estimate_concrete_volume_m3(dam_height_m: float, dam_length_m: float,
                                valley_shape_factor: float = VALLEY_SHAPE_FACTOR) -> float:
    """Gravity dam concrete volume estimate: triangular cross-section (base_width = ratio * height)
    integrated across a valley profile (valley_shape_factor = 0.5 by default for a realistic
    trapezoidal gorge; 1.0 for a pure rectangular slot extrusion, ~0.33 for a sharp V-notch).
    Both dam_height_m and dam_length_m should be >= 0; returns 0 for a non-positive height or length."""
    if dam_height_m <= 0 or dam_length_m <= 0:
        return 0.0
    base_width_m = GRAVITY_DAM_BASE_TO_HEIGHT_RATIO * dam_height_m
    cross_section_area_m2 = 0.5 * base_width_m * dam_height_m
    return cross_section_area_m2 * dam_length_m * valley_shape_factor
