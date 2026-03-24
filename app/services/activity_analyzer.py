import gzip
import json
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings


RESTING_HR = 60  # Estimated resting HR for TRIMP calculation

# Zone weights for Relative Effort (exponential - harder zones count much more)
ZONE_WEIGHTS = {1: 1.0, 2: 1.5, 3: 2.0, 4: 3.0, 5: 4.5}


@dataclass
class AnalysisResult:
    zone1_pct: float = 0.0
    zone2_pct: float = 0.0
    zone3_pct: float = 0.0
    zone4_pct: float = 0.0
    zone5_pct: float = 0.0
    zone1_seconds: int = 0
    zone2_seconds: int = 0
    zone3_seconds: int = 0
    zone4_seconds: int = 0
    zone5_seconds: int = 0
    pace_cv: Optional[float] = None
    avg_cadence: Optional[float] = None
    effort_score: Optional[int] = None
    flags: List[str] = field(default_factory=list)
    coach_comment: str = ""


def classify_hr_zone(bpm: float) -> int:
    """Return zone number (1-5) for a given heart rate."""
    if bpm < settings.zone1_ceiling:
        return 1
    elif bpm <= settings.zone2_ceiling:
        return 2
    elif bpm <= settings.zone3_ceiling:
        return 3
    elif bpm <= settings.zone4_ceiling:
        return 4
    else:
        return 5


def compute_zone_distribution(
    hr_data: List[float],
    time_data: Optional[List[int]] = None,
) -> dict:
    """Compute percentage and seconds in each HR zone from stream data."""
    if not hr_data:
        return {}

    zone_seconds = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for i, bpm in enumerate(hr_data):
        if bpm <= 0:
            continue
        zone = classify_hr_zone(bpm)
        # Use time stream for accurate deltas, fall back to 1s per sample
        if time_data and i > 0:
            delta = time_data[i] - time_data[i - 1]
            delta = max(0, min(delta, 10))  # clamp to avoid gaps
        else:
            delta = 1
        zone_seconds[zone] += delta

    total = sum(zone_seconds.values())
    if total == 0:
        return {}

    result = {}
    for z in range(1, 6):
        result[f"zone{z}_pct"] = round(zone_seconds[z] / total * 100, 1)
        result[f"zone{z}_seconds"] = zone_seconds[z]
    return result


def compute_relative_effort(
    hr_data: List[float],
    time_data: Optional[List[int]] = None,
    total_elevation: float = 0.0,
) -> Optional[int]:
    """Compute Relative Effort using hrTSS formula (same method as Strava).

    Based on Lactate Threshold HR (LTHR), not max HR.
    LTHR is estimated as the Zone 3/4 boundary (zone3_ceiling).

    Formula per second:
      intensity = HR / LTHR
      trimp += (delta_minutes) * intensity * k
    where k is an exponential weighting factor:
      k = e^(1.92 * intensity)

    Normalized so that 60 min at LTHR = 100.
    """
    if not hr_data:
        return None

    import math

    # LTHR = Zone 3 ceiling (boundary between Tempo and Threshold)
    lthr = settings.zone3_ceiling
    if lthr <= 0:
        lthr = 168  # fallback

    # Normalization factor: what 60 min at exactly LTHR would score
    norm_intensity = 1.0
    norm_k = math.exp(1.92 * norm_intensity)
    norm_60min = 60.0 * norm_intensity * norm_k  # reference value for scaling

    trimp = 0.0

    for i, bpm in enumerate(hr_data):
        if bpm <= 0:
            continue

        # Time delta in minutes
        if time_data and i > 0:
            delta_s = time_data[i] - time_data[i - 1]
            delta_s = max(0, min(delta_s, 10))  # clamp gaps
        else:
            delta_s = 1
        delta_min = delta_s / 60.0

        # Intensity relative to LTHR
        intensity = bpm / lthr
        intensity = max(0.0, min(intensity, 1.5))  # clamp extreme values

        # Exponential weighting - time above LTHR counts much more
        k = math.exp(1.92 * intensity)

        trimp += delta_min * intensity * k

    # Scale so 60 min at LTHR = 100
    score = int(round(trimp / norm_60min * 100))
    return max(1, min(300, score))


def compute_splits(streams: dict, split_distance_m: float = 1000.0) -> List[dict]:
    """Compute km-by-km splits with pace, HR, and elevation."""
    distance_data = streams.get("distance", {}).get("data", [])
    time_data = streams.get("time", {}).get("data", [])
    if not distance_data or not time_data or len(distance_data) != len(time_data):
        return []

    hr_data = streams.get("heartrate", {}).get("data", [])
    alt_data = streams.get("altitude", {}).get("data", [])
    has_hr = len(hr_data) == len(distance_data)
    has_alt = len(alt_data) == len(distance_data)

    splits = []
    split_start_idx = 0
    split_num = 1
    next_boundary = split_distance_m

    for i in range(len(distance_data)):
        if distance_data[i] >= next_boundary or i == len(distance_data) - 1:
            is_last = i == len(distance_data) - 1
            # Actual distance and time for this split
            dist = distance_data[i] - (distance_data[split_start_idx] if split_start_idx > 0 else 0)
            elapsed = time_data[i] - time_data[split_start_idx]

            if dist <= 0 or elapsed <= 0:
                split_start_idx = i
                next_boundary += split_distance_m
                split_num += 1
                continue

            # Pace in seconds per km
            pace_s_per_km = elapsed / (dist / 1000)
            pace_min = int(pace_s_per_km // 60)
            pace_sec = int(pace_s_per_km % 60)

            # Avg HR for this split
            avg_hr = None
            if has_hr:
                hr_slice = [h for h in hr_data[split_start_idx:i + 1] if h > 0]
                if hr_slice:
                    avg_hr = round(sum(hr_slice) / len(hr_slice))

            # Elevation for this split
            elev = 0
            if has_alt:
                elev = round(alt_data[i] - alt_data[split_start_idx])

            # Label: full km or partial
            if is_last and dist < split_distance_m * 0.9:
                km_label = round(dist / 1000, 1)
            else:
                km_label = split_num

            splits.append({
                "km": km_label,
                "pace": f"{pace_min}:{pace_sec:02d}",
                "pace_seconds": round(pace_s_per_km),
                "avg_hr": avg_hr,
                "elevation": elev,
            })

            split_start_idx = i
            next_boundary += split_distance_m
            split_num += 1

    return splits


def compute_pace_zones(
    velocity_data: List[float],
    time_data: Optional[List[int]] = None,
) -> Optional[List[dict]]:
    """Compute pace zone distribution based on target HM time.

    Pace zones (Daniels-style, relative to HM race pace):
      Z1 Easy:      > 115% of race pace (slower)
      Z2 Moderate:  105-115% of race pace
      Z3 Tempo/HM:  98-105% of race pace
      Z4 Threshold: 92-98% of race pace
      Z5 Interval:  < 92% of race pace (faster)

    Note: pace is in s/km, so "slower" = higher number.
    """
    if not velocity_data:
        return None

    hm_pace = (settings.target_hm_time_minutes * 60) / 21.0975  # s/km

    # Zone boundaries in s/km (higher = slower)
    boundaries = {
        "z5_max": hm_pace * 0.92,   # faster than this = Z5
        "z4_max": hm_pace * 0.98,
        "z3_max": hm_pace * 1.05,
        "z2_max": hm_pace * 1.15,
        # slower = Z1
    }

    zone_seconds = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

    for i, v in enumerate(velocity_data):
        if v < 0.5:  # skip stops
            continue

        if time_data and i > 0:
            delta = time_data[i] - time_data[i - 1]
            delta = max(0, min(delta, 10))
        else:
            delta = 1

        pace = 1000.0 / v  # s/km

        if pace <= boundaries["z5_max"]:
            zone_seconds[5] += delta
        elif pace <= boundaries["z4_max"]:
            zone_seconds[4] += delta
        elif pace <= boundaries["z3_max"]:
            zone_seconds[3] += delta
        elif pace <= boundaries["z2_max"]:
            zone_seconds[2] += delta
        else:
            zone_seconds[1] += delta

    total = sum(zone_seconds.values())
    if total == 0:
        return None

    zone_names = {
        1: "Easy",
        2: "Moderate",
        3: "Tempo",
        4: "Threshold",
        5: "Interval",
    }
    zone_colors = {
        1: "#4CAF50",
        2: "#2196F3",
        3: "#FF9800",
        4: "#f44336",
        5: "#9C27B0",
    }

    # Format boundary paces for display
    def fmt_pace(s_per_km: float) -> str:
        m = int(s_per_km // 60)
        s = int(s_per_km % 60)
        return f"{m}:{s:02d}"

    pace_ranges = {
        1: f"> {fmt_pace(boundaries['z2_max'])}/km",
        2: f"{fmt_pace(boundaries['z3_max'])}-{fmt_pace(boundaries['z2_max'])}/km",
        3: f"{fmt_pace(boundaries['z4_max'])}-{fmt_pace(boundaries['z3_max'])}/km",
        4: f"{fmt_pace(boundaries['z5_max'])}-{fmt_pace(boundaries['z4_max'])}/km",
        5: f"< {fmt_pace(boundaries['z5_max'])}/km",
    }

    result = []
    for z in range(1, 6):
        pct = round(zone_seconds[z] / total * 100, 1)
        result.append({
            "zone": z,
            "name": zone_names[z],
            "color": zone_colors[z],
            "pct": pct,
            "seconds": zone_seconds[z],
            "pace_range": pace_ranges[z],
        })
    return result


def compute_pace_cv(velocity_data: list) -> Optional[float]:
    """Compute coefficient of variation for pace stability.
    Lower CV = more consistent pace. CV > 0.15 on easy runs = inconsistent.
    """
    # Filter out zero/near-zero values (stops, pauses)
    valid = [v for v in velocity_data if v > 0.5]
    if len(valid) < 10:
        return None

    mean = statistics.mean(valid)
    if mean == 0:
        return None

    return round(statistics.stdev(valid) / mean, 3)


def is_long_run(distance_m: float, name: str) -> bool:
    """Determine if an activity is a long run based on distance or name."""
    name_lower = name.lower()
    if any(kw in name_lower for kw in ["long run", "lang tur", "langtur", "long"]):
        return True
    return distance_m >= 12_000  # 12km+


def generate_coach_comment(
    result: AnalysisResult,
    distance_m: float,
    name: str,
    avg_hr: Optional[float],
) -> str:
    """Generate a coaching comment in Danish with emojis."""
    comments = []
    distance_km = distance_m / 1000

    if "long_run_too_fast" in result.flags:
        comments.append(
            f"⚠️ Din long run var for hurtig! Gennemsnitspuls {avg_hr:.0f} bpm er over Zone 2-loftet (141 bpm). "
            f"Jeg ved det er svært at holde igen, men Zone 2-træning bygger din aerobe base - "
            f"det er DEN der bærer dig over målstregen med overskud. "
            f"Prøv at tænke 'kan jeg føre en samtale?' næste gang. 🗣️"
        )

    if "low_cadence" in result.flags:
        comments.append(
            f"👟 Din kadence ({result.avg_cadence:.0f} spm) er lidt lav. "
            f"Prøv at sigte mod 170+ skridt/minut - kortere, hurtigere skridt mindsker belastningen på dine led."
        )

    if "inconsistent_pace" in result.flags:
        comments.append(
            f"📊 Din pace varierede en del (CV: {result.pace_cv:.2f}). "
            f"Prøv at holde en jævnere pace - det træner kroppen til at være effektiv."
        )

    if not result.flags:
        if result.zone2_pct > 70:
            comments.append(
                f"✅ Flot! {distance_km:.1f} km solidt i Zone 2 ({result.zone2_pct:.0f}% af tiden). "
                f"Præcis sådan bygger du den aerobe motor. Stærkt arbejde! 💪"
            )
        elif result.zone4_pct > 30 or result.zone5_pct > 20:
            comments.append(
                f"🔥 Hård session! Du brugte {result.zone4_pct + result.zone5_pct:.0f}% af tiden i Zone 4/5. "
                f"God intensitet - husk at give kroppen tid til at restituere efter den her."
            )
        else:
            comments.append(
                f"👍 Fint løb! {distance_km:.1f} km i kassen. "
                f"Zone-fordeling: Z1 {result.zone1_pct:.0f}% | Z2 {result.zone2_pct:.0f}% | "
                f"Z3 {result.zone3_pct:.0f}% | Z4 {result.zone4_pct:.0f}% | Z5 {result.zone5_pct:.0f}%"
            )

    return " ".join(comments)


def analyze_activity(
    name: str,
    distance_m: float,
    avg_hr: Optional[float],
    streams: dict,
) -> AnalysisResult:
    """Full analysis of an activity using stream data."""
    result = AnalysisResult()

    # HR zone analysis
    hr_stream = streams.get("heartrate", {}).get("data", [])
    time_stream = streams.get("time", {}).get("data", [])
    if hr_stream:
        zones = compute_zone_distribution(hr_stream, time_stream or None)
        result.zone1_pct = zones.get("zone1_pct", 0.0)
        result.zone2_pct = zones.get("zone2_pct", 0.0)
        result.zone3_pct = zones.get("zone3_pct", 0.0)
        result.zone4_pct = zones.get("zone4_pct", 0.0)
        result.zone5_pct = zones.get("zone5_pct", 0.0)
        result.zone1_seconds = zones.get("zone1_seconds", 0)
        result.zone2_seconds = zones.get("zone2_seconds", 0)
        result.zone3_seconds = zones.get("zone3_seconds", 0)
        result.zone4_seconds = zones.get("zone4_seconds", 0)
        result.zone5_seconds = zones.get("zone5_seconds", 0)

        # Compute Relative Effort from streams
        result.effort_score = compute_relative_effort(
            hr_stream, time_stream or None, 0.0
        )

        # Flag: long run too fast
        if is_long_run(distance_m, name) and avg_hr and avg_hr > settings.zone2_ceiling:
            result.flags.append("long_run_too_fast")

    # Pace analysis
    velocity_stream = streams.get("velocity_smooth", {}).get("data", [])
    if velocity_stream:
        result.pace_cv = compute_pace_cv(velocity_stream)
        if result.pace_cv and result.pace_cv > 0.15 and is_long_run(distance_m, name):
            result.flags.append("inconsistent_pace")

    # Cadence analysis
    cadence_stream = streams.get("cadence", {}).get("data", [])
    if cadence_stream:
        valid_cadence = [c * 2 for c in cadence_stream if c > 0]  # Strava reports half-cadence
        if valid_cadence:
            result.avg_cadence = round(statistics.mean(valid_cadence), 1)
            if result.avg_cadence < 170:
                result.flags.append("low_cadence")

    result.coach_comment = generate_coach_comment(result, distance_m, name, avg_hr)
    return result


def compute_effort_score(
    moving_time_s: int,
    avg_hr: Optional[float],
    max_hr_activity: Optional[float],
    distance_m: float,
    total_elevation: float,
) -> Optional[int]:
    """Compute TRIMP-based effort score (0-100+).

    Uses Training Impulse formula with zone weighting.
    A typical easy 5km ~20, hard 10km ~50, long 15km ~65, race HM ~95.
    """
    if not avg_hr or not moving_time_s:
        return None

    max_hr = settings.max_heart_rate
    duration_min = moving_time_s / 60

    # Heart rate reserve fraction
    hr_reserve = (avg_hr - RESTING_HR) / (max_hr - RESTING_HR)
    hr_reserve = max(0.0, min(1.0, hr_reserve))

    # Zone weighting factor (exponential - harder effort counts more)
    zone_factor = 1.0
    if avg_hr < settings.zone1_ceiling:
        zone_factor = 0.8
    elif avg_hr <= settings.zone2_ceiling:
        zone_factor = 1.0
    elif avg_hr <= settings.zone3_ceiling:
        zone_factor = 1.2
    elif avg_hr <= settings.zone4_ceiling:
        zone_factor = 1.6
    else:
        zone_factor = 2.0

    # Base TRIMP
    trimp = duration_min * hr_reserve * zone_factor

    # Elevation bonus (10% extra per 100m gained)
    if total_elevation > 0:
        elev_bonus = 1.0 + (total_elevation / 1000)
        trimp *= elev_bonus

    # Normalize to ~0-100 scale (60 min zone 4 run = ~80)
    score = int(round(trimp / 1.2))
    return max(1, min(150, score))


def generate_strava_description(
    name: str,
    distance_m: float,
    moving_time_s: int,
    avg_hr: Optional[float],
    result: AnalysisResult,
    shoe_info: Optional[str] = None,
    plan_week: Optional[int] = None,
    plan_total_weeks: Optional[int] = None,
) -> str:
    """Generate a Strava activity description ready for copy-paste."""
    distance_km = distance_m / 1000
    pace_s_per_km = moving_time_s / (distance_km) if distance_km > 0 else 0
    pace_min = int(pace_s_per_km // 60)
    pace_sec = int(pace_s_per_km % 60)

    # Determine workout type
    if is_long_run(distance_m, name):
        workout_label = "Long Run"
    elif result.zone4_pct + result.zone5_pct > 40:
        workout_label = "Interval/Tempo"
    else:
        workout_label = "Easy Run"

    lines = []
    lines.append(f"\U0001f3c3 {workout_label} | {distance_km:.1f} km | {pace_min}:{pace_sec:02d}/km")

    # HR zones
    if avg_hr:
        zones = []
        if result.zone2_pct > 5:
            zones.append(f"Z2: {result.zone2_pct:.0f}%")
        if result.zone3_pct > 5:
            zones.append(f"Z3: {result.zone3_pct:.0f}%")
        if result.zone4_pct > 5:
            zones.append(f"Z4: {result.zone4_pct:.0f}%")
        if result.zone5_pct > 5:
            zones.append(f"Z5: {result.zone5_pct:.0f}%")
        if zones:
            lines.append("\u2764\ufe0f " + " | ".join(zones))

    # Effort score
    if result.effort_score:
        lines.append(f"\U0001f4aa Effort: {result.effort_score}/100")

    # Pace stability
    if result.pace_cv is not None:
        stability = "stabil" if result.pace_cv < 0.10 else "ok" if result.pace_cv < 0.15 else "varierende"
        lines.append(f"\U0001f4ca Pace CV: {result.pace_cv:.2f} ({stability})")

    # Shoe info
    if shoe_info:
        lines.append(f"\U0001f45f {shoe_info}")

    # Plan progress
    if plan_week and plan_total_weeks:
        lines.append(f"\U0001f3af Uge {plan_week}/{plan_total_weeks} mod Aarhus HM")

    # Coach comment (shortened)
    if result.coach_comment:
        short_comment = result.coach_comment.split(".")[0] + "."
        if len(short_comment) > 80:
            short_comment = short_comment[:77] + "..."
        lines.append(f"\U0001f4ac {short_comment}")

    return "\n".join(lines)


def compress_streams(streams: dict) -> str:
    """Compress stream data for storage."""
    json_bytes = json.dumps(streams).encode()
    compressed = gzip.compress(json_bytes)
    import base64
    return base64.b64encode(compressed).decode()


def decompress_streams(data: str) -> dict:
    """Decompress stored stream data."""
    import base64
    compressed = base64.b64decode(data.encode())
    json_bytes = gzip.decompress(compressed)
    return json.loads(json_bytes)
