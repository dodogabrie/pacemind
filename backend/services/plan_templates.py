"""Pre-built training plan templates for common race types.

Each template defines weekly volume progression and workout type distribution.
The agent customizes distances/paces based on user's fitness and race profile.
"""

# TODO(coach-review #62 — see GH issues): library is thin (~10 generic templates).
# Competitors advertise 500+ named coach-authored plans. Expand to 50-100 named
# archetypes (Pfitzinger 18/55, Hanson Beginner, Daniels 2Q, Koop 100mi, Vert.run
# CCC, Uphill Athlete Big Mountain) with author + methodology_ref + target_population.
# Surface a "Pick a starting framework" wizard in onboarding; engine consumes
# base_template_id and applies user constraints on top.

PLAN_TEMPLATES = [
    {
        "id": "trail_30k_6w",
        "name": "Trail 30K (6 weeks)",
        "description": "6-week plan for a 30km trail race. Base → Build → Peak → Taper.",
        "race_type": "trail",
        "distance_km": 30,
        "duration_weeks": 6,
        "phases": [
            {"weeks": [1, 2], "phase": "Base Building", "volume_pct": 70},
            {"weeks": [3, 4], "phase": "Build", "volume_pct": 90},
            {"weeks": [5], "phase": "Peak", "volume_pct": 100},
            {"weeks": [6], "phase": "Taper", "volume_pct": 50},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "intervals",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "recovery",
        },
    },
    {
        "id": "trail_50k_10w",
        "name": "Trail 50K (10 weeks)",
        "description": "10-week plan for a 50km trail/ultra race. Progressive build with proper taper.",
        "race_type": "trail",
        "distance_km": 50,
        "duration_weeks": 10,
        "phases": [
            {"weeks": [1, 2, 3], "phase": "Base Building", "volume_pct": 65},
            {"weeks": [4, 5, 6], "phase": "Build", "volume_pct": 85},
            {"weeks": [7, 8], "phase": "Peak", "volume_pct": 100},
            {"weeks": [9], "phase": "Pre-Taper", "volume_pct": 70},
            {"weeks": [10], "phase": "Taper", "volume_pct": 40},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "recovery",
        },
    },
    {
        "id": "trail_80k_16w",
        "name": "Trail 80K / Ultra (16 weeks)",
        "description": "16-week ultra trail plan. Long progressive build, back-to-back weekends, extended taper.",
        "race_type": "trail",
        "distance_km": 80,
        "duration_weeks": 16,
        "phases": [
            {"weeks": [1, 2, 3, 4], "phase": "Base Building", "volume_pct": 60},
            {"weeks": [5, 6, 7, 8], "phase": "Build 1", "volume_pct": 80},
            {"weeks": [9, 10, 11], "phase": "Build 2", "volume_pct": 95},
            {"weeks": [12, 13], "phase": "Peak", "volume_pct": 100},
            {"weeks": [14], "phase": "Pre-Taper", "volume_pct": 70},
            {"weeks": [15, 16], "phase": "Taper", "volume_pct": 40},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "easy",
        },
    },
    {
        "id": "road_marathon_12w",
        "name": "Road Marathon (12 weeks)",
        "description": "12-week road marathon plan. Classic Daniels-inspired periodization.",
        "race_type": "road",
        "distance_km": 42.2,
        "duration_weeks": 12,
        "phases": [
            {"weeks": [1, 2, 3], "phase": "Base Building", "volume_pct": 70},
            {"weeks": [4, 5, 6], "phase": "Build", "volume_pct": 85},
            {"weeks": [7, 8, 9], "phase": "Peak", "volume_pct": 100},
            {"weeks": [10, 11], "phase": "Pre-Taper", "volume_pct": 75},
            {"weeks": [12], "phase": "Taper", "volume_pct": 40},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "intervals",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "recovery",
        },
    },
    # --- Additional templates based on established coaching methodology ---
    {
        "id": "vk_race_8w",
        "name": "Vertical Kilometer (8 weeks)",
        "description": "8-week plan for a VK or steep skyrace (<5km, ~1000m D+). Hill sprints, muscular endurance, and Z4 intervals. Based on established mountain running coaching methodology.",
        "race_type": "trail",
        "distance_km": 5,
        "duration_weeks": 8,
        "phases": [
            {"weeks": [1, 2], "phase": "Base + Strength", "volume_pct": 70},
            {"weeks": [3, 4], "phase": "Muscular Endurance", "volume_pct": 85},
            {"weeks": [5, 6], "phase": "Z4 Power + Specificity", "volume_pct": 100},
            {"weeks": [7], "phase": "Sharpening", "volume_pct": 70},
            {"weeks": [8], "phase": "Taper", "volume_pct": 40},
        ],
        "weekly_structure": {
            "Monday": "recovery",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "intervals",
            "Friday": "rest",
            "Saturday": "vert_session",
            "Sunday": "easy",
        },
    },
    {
        "id": "trail_half_marathon_8w",
        "name": "Trail Half-Marathon (8 weeks)",
        "description": "8-week plan for a trail half-marathon. Balances speed and endurance with hill technique. Good first goal race for trail beginners. Based on established trail running coaching methodology.",
        "race_type": "trail",
        "distance_km": 21.1,
        "duration_weeks": 8,
        "phases": [
            {"weeks": [1, 2], "phase": "Base + Consistency", "volume_pct": 70},
            {"weeks": [3, 4, 5], "phase": "Build (Speed + Hills)", "volume_pct": 90},
            {"weeks": [6], "phase": "Peak", "volume_pct": 100},
            {"weeks": [7], "phase": "Pre-Taper", "volume_pct": 70},
            {"weeks": [8], "phase": "Taper", "volume_pct": 45},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "intervals",
            "Wednesday": "easy",
            "Thursday": "hill_repeats",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "recovery",
        },
    },
    {
        "id": "skyrace_30k_10w",
        "name": "Skyrace / Technical 30K (10 weeks)",
        "description": "10-week plan for a technical skyrace or mountain 30K with 2000m+ D+. Hill strength, downhill technique, muscular endurance. Based on established mountain running coaching methodology.",
        "race_type": "trail",
        "distance_km": 30,
        "duration_weeks": 10,
        "phases": [
            {"weeks": [1, 2, 3], "phase": "Base + Hill Strength", "volume_pct": 70},
            {"weeks": [4, 5, 6], "phase": "Build (ME + Z3)", "volume_pct": 90},
            {"weeks": [7, 8], "phase": "Peak (Z4 + Race Sim)", "volume_pct": 100},
            {"weeks": [9], "phase": "Pre-Taper", "volume_pct": 65},
            {"weeks": [10], "phase": "Taper", "volume_pct": 40},
        ],
        "weekly_structure": {
            "Monday": "recovery",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "intervals",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "easy",
        },
    },
    {
        "id": "trail_50mi_16w",
        "name": "Trail 50 Mile (16 weeks)",
        "description": "16-week plan for a 50-mile trail ultra. Back-to-back weekends, gut training, progressive volume with mid-plan recovery. Based on established ultra-endurance coaching methodology.",
        "race_type": "trail",
        "distance_km": 80,
        "duration_weeks": 16,
        "phases": [
            {"weeks": [1, 2, 3, 4], "phase": "Base Building", "volume_pct": 55},
            {"weeks": [5, 6, 7], "phase": "Build 1 (Volume)", "volume_pct": 75},
            {"weeks": [8], "phase": "Recovery", "volume_pct": 50},
            {"weeks": [9, 10, 11], "phase": "Build 2 (Specificity)", "volume_pct": 90},
            {"weeks": [12, 13], "phase": "Peak + Back-to-backs", "volume_pct": 100},
            {"weeks": [14], "phase": "Pre-Taper", "volume_pct": 65},
            {"weeks": [15, 16], "phase": "Taper", "volume_pct": 35},
        ],
        "weekly_structure": {
            "Monday": "recovery",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "back_to_back",
        },
    },
    {
        "id": "trail_100mi_24w",
        "name": "Trail 100 Mile (24 weeks)",
        "description": "24-week plan for a 100-mile trail ultra. Stepping-stone races (50K, 50mi), progressive long runs past marathon, back-to-back weekends, 3-week taper. Based on established ultra-endurance coaching methodology for experienced athletes.",
        "race_type": "trail",
        "distance_km": 160,
        "duration_weeks": 24,
        "phases": [
            {"weeks": [1, 2, 3, 4, 5], "phase": "Base Building", "volume_pct": 50},
            {"weeks": [6, 7, 8], "phase": "Build 1 (Volume)", "volume_pct": 70},
            {"weeks": [9], "phase": "Recovery", "volume_pct": 45},
            {"weeks": [10, 11, 12], "phase": "Build 2 (50K Stepping Stone)", "volume_pct": 85},
            {"weeks": [13], "phase": "Recovery", "volume_pct": 45},
            {"weeks": [14, 15, 16, 17], "phase": "Build 3 (50mi Stepping Stone)", "volume_pct": 95},
            {"weeks": [18], "phase": "Recovery", "volume_pct": 50},
            {"weeks": [19, 20], "phase": "Peak", "volume_pct": 100},
            {"weeks": [21], "phase": "Pre-Taper", "volume_pct": 65},
            {"weeks": [22, 23, 24], "phase": "Taper", "volume_pct": 35},
        ],
        "weekly_structure": {
            "Monday": "recovery",
            "Tuesday": "hill_repeats",
            "Wednesday": "easy",
            "Thursday": "tempo",
            "Friday": "easy",
            "Saturday": "long_run",
            "Sunday": "back_to_back",
        },
    },
    {
        "id": "cat1_base_12w",
        "name": "Base Building — Cat 1 Athlete (12 weeks)",
        "description": "12-week aerobic base plan for athletes new to structured training (<400 hrs/year). Pure Z1-Z2 volume, general strength, no high-intensity. Based on Uphill Athlete Cat 1 methodology.",
        "race_type": "trail",
        "distance_km": 0,
        "duration_weeks": 12,
        "phases": [
            {"weeks": [1, 2], "phase": "Transition", "volume_pct": 50},
            {"weeks": [3, 4, 5], "phase": "Base 1 (Volume Focus)", "volume_pct": 70},
            {"weeks": [6], "phase": "Recovery", "volume_pct": 45},
            {"weeks": [7, 8, 9], "phase": "Base 2 (Volume + Strength)", "volume_pct": 85},
            {"weeks": [10], "phase": "Recovery", "volume_pct": 50},
            {"weeks": [11, 12], "phase": "Base 3 (Preparing for Intensity)", "volume_pct": 100},
        ],
        "weekly_structure": {
            "Monday": "easy",
            "Tuesday": "easy",
            "Wednesday": "cross_train",
            "Thursday": "easy",
            "Friday": "rest",
            "Saturday": "long_run",
            "Sunday": "recovery",
        },
    },
]


def get_templates() -> list:
    """Return all available plan templates."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "description": t["description"],
            "race_type": t["race_type"],
            "distance_km": t["distance_km"],
            "duration_weeks": t["duration_weeks"],
            "phases": t["phases"],
        }
        for t in PLAN_TEMPLATES
    ]


def get_template_detail(template_id: str) -> dict | None:
    """Return full template including weekly structure."""
    for t in PLAN_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None
