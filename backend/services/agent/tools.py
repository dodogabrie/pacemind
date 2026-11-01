"""Tool definitions for the LLM prediction agent.

Each tool maps to a Claude API tool_use schema definition.
"""

# User-friendly labels shown in the UI during tool execution
TOOL_DISPLAY_NAMES = {
    "get_current_params": "Reading model parameters...",
    "adjust_params": "Adjusting parameters...",
    "get_tier_status": "Checking prediction tier...",
    "run_prediction": "Running prediction...",
    "compare_predictions": "Comparing predictions...",
    "retrain_model": "Retraining model...",
    "rollback_params": "Rolling back parameters...",
    "list_gpx_routes": "Loading your routes...",
    "get_terrain_analysis": "Analyzing terrain...",
    "get_weather_conditions": "Checking weather conditions...",
    "get_training_load": "Analyzing training load...",
    "get_race_briefing": "Preparing race briefing...",
    "get_pacing_strategy": "Generating pacing strategy...",
    "get_past_performance": "Analyzing past performance...",
    "get_nutrition_estimate": "Estimating nutrition needs...",
    "suggest_waypoints": "Suggesting waypoints...",
    "manage_annotations": "Managing annotations...",
    "get_route_segments": "Loading route segments...",
    "get_equipment_suggestion": "Suggesting equipment...",
    "get_training_history": "Loading training history...",
    "get_performance_trends": "Analyzing performance trends...",
    "get_race_profile": "Analyzing race profile...",
    "generate_training_week": "Generating training week...",
    "save_training_plan": "Saving training plan...",
    "get_plan_compliance": "Checking plan compliance...",
    "inspect_training_plan": "Inspecting training plan...",
    "adjust_training_week": "Adjusting training week...",
    "get_plan_templates": "Loading plan templates...",
    "get_season_overview": "Loading season overview...",
    "generate_race_report": "Generating race report...",
    "get_race_report": "Loading race report...",
    "lookup_coaching_knowledge": "Consulting coaching knowledge...",
    "assess_training_readiness": "Assessing training readiness...",
    "generate_full_plan": "Building training plan...",
    "get_training_preferences": "Loading training preferences...",
    "save_training_preferences": "Saving training preferences...",
    "raise_long_run_cap": "Updating long run cap...",
    "search_tuneup_races": "Searching tune-up races...",
    "start_onboarding_questionnaire": "Preparing onboarding wizard...",
    "preview_capacity": "Computing capacity preview...",
    "infer_terrain_profile": "Analyzing terrain profile...",
    "match_routes_to_plan": "Matching routes to plan...",
    "get_route_gpx_link": "Preparing GPX link...",
    "list_activities": "Listing activities...",
    "get_activity_detail": "Analysing workout...",
    "compare_to_plan": "Comparing workout to plan...",
    "get_segment_improvement": "Finding the same stretch in past runs...",
}

AGENT_TOOLS = [
    {
        "name": "get_current_params",
        "description": (
            "Get the user's current physics model parameters. Returns parameter values, "
            "whether they are learned from data or defaults, and parameter bounds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "adjust_params",
        "description": (
            "Modify one or more physics parameters. Each parameter change is validated "
            "against bounds and magnitude limits (max 30% of range per adjustment). "
            "A snapshot is created before changes for rollback. "
            "Parameters: v_flat (flat speed m/s, 2.0-5.0), k_up (uphill coeff, 0.8-1.5), "
            "k_tech (technical coeff, 0.8-1.2), fatigue_alpha (fatigue rate, 0.1-0.6), "
            "a_param (downhill exponent, 1.0-6.0), k_terrain_up/down/flat (surface factors)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "adjustments": {
                    "type": "object",
                    "description": "Parameter name to new value mapping, e.g. {\"k_up\": 1.2, \"v_flat\": 3.5}",
                    "additionalProperties": {"type": "number"}
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation for the adjustment"
                }
            },
            "required": ["adjustments", "reason"]
        }
    },
    {
        "name": "get_tier_status",
        "description": (
            "Get the user's current prediction tier, activity count, progress toward "
            "the next tier, and measured accuracy (p80_pct: past predictions were within "
            "this % 8 times out of 10, over n runs). Tiers: 1 (physics, default params, "
            "0-4 runs), 2 (physics calibrated on the last 10 runs, 5+ runs)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "run_prediction",
        "description": (
            "Run a prediction on a GPX route using current parameters. "
            "Returns finish time (moving + stops), segment breakdown, 80% interval, and tier used."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route to predict"
                },
                "effort": {
                    "type": "string",
                    "enum": ["race", "training", "recovery"],
                    "description": "Effort level (default: race)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "compare_predictions",
        "description": (
            "Compare predictions on the same route with two different parameter sets. "
            "Useful for showing before/after effects of parameter changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route to compare"
                },
                "params_a": {
                    "type": "object",
                    "description": "First parameter set (e.g. current params)",
                    "additionalProperties": {"type": "number"}
                },
                "params_b": {
                    "type": "object",
                    "description": "Second parameter set (e.g. adjusted params)",
                    "additionalProperties": {"type": "number"}
                }
            },
            "required": ["gpx_id", "params_a", "params_b"]
        }
    },
    {
        "name": "retrain_model",
        "description": (
            "Re-learn parameters from the user's activity history: the physics params "
            "and the personal-habits model, which is used only if it beat the physics "
            "params on the user's own past runs (see personal_model in the result). "
            "This resets any manual adjustments made by the agent."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "rollback_params",
        "description": (
            "Undo the last parameter change by restoring from snapshot. "
            "Returns the restored parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_gpx_routes",
        "description": (
            "List the user's uploaded GPX routes with basic info "
            "(id, name, distance, elevation gain)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_terrain_analysis",
        "description": (
            "Analyze terrain types along a GPX route using OpenStreetMap data. "
            "Returns surface breakdown (% road, trail, technical, gravel, mud), "
            "per-segment terrain factors, and difficulty rating. "
            "Use this to understand route characteristics before giving pacing advice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route to analyze"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "get_weather_conditions",
        "description": (
            "Get weather conditions for a route on a specific date. "
            "Returns temperature, humidity, wind, precipitation, and a computed "
            "performance impact factor. Use historical mode for past activities "
            "or forecast mode for upcoming races/runs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (optional, defaults to today)"
                },
                "mode": {
                    "type": "string",
                    "enum": ["historical", "forecast"],
                    "description": "Whether to fetch historical or forecast data (default: forecast)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "get_training_load",
        "description": (
            "Get the user's current training load metrics: "
            "ATL (acute 7-day load), CTL (chronic 42-day fitness), "
            "TSB (freshness = CTL - ATL), recent volume, and form interpretation. "
            "Use this to understand if the runner is fresh, fatigued, or building fitness."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_race_briefing",
        "description": (
            "Generate a comprehensive pre-race briefing combining terrain analysis, "
            "weather forecast, training load status, and time prediction into one "
            "structured summary. This is the primary tool for race day preparation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "race_date": {
                    "type": "string",
                    "description": "Race date in YYYY-MM-DD format (optional, defaults to today)"
                },
                "effort": {
                    "type": "string",
                    "enum": ["race", "training", "recovery"],
                    "description": "Effort level (default: race)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "get_pacing_strategy",
        "description": (
            "Generate a pacing strategy with suggested splits for each major section "
            "of a route, accounting for terrain type, gradient, altitude, weather, "
            "and fatigue accumulation. Returns per-km target paces."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "effort": {
                    "type": "string",
                    "enum": ["race", "training", "recovery"],
                    "description": "Effort level (default: race)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "get_past_performance",
        "description": (
            "Analyze the user's historical performance to identify strengths and weaknesses. "
            "Examines residuals across different terrain types, grades, and distances "
            "to find patterns like 'strong climber but loses time on technical descents'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_nutrition_estimate",
        "description": (
            "Estimate calorie and hydration needs for a route based on predicted duration, "
            "elevation gain, and weather conditions. Returns recommended intake per hour "
            "and total requirements."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "runner_weight_kg": {
                    "type": "number",
                    "description": "Runner's weight in kg (default: 70)"
                },
                "race_date": {
                    "type": "string",
                    "description": "Date for weather lookup (YYYY-MM-DD, optional)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "suggest_waypoints",
        "description": (
            "Propose waypoints for the user to review and accept/dismiss. "
            "Use after analyzing terrain or route segments to suggest strategic points "
            "like aid stations, water stops, checkpoints, or caution zones. "
            "The user will see suggestion cards in the chat and dashed markers on the map."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "waypoints": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "distance_km": {
                                "type": "number",
                                "description": "Distance along route in km"
                            },
                            "type": {
                                "type": "string",
                                "enum": ["aid_station", "generic", "water", "checkpoint", "caution"],
                                "description": "Waypoint type"
                            },
                            "label": {
                                "type": "string",
                                "description": "Short label for the waypoint"
                            },
                            "stop_time_seconds": {
                                "type": "integer",
                                "description": "Suggested stop time in seconds (default: aid_station=60, water=30, others=0)"
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why this waypoint is suggested here"
                            }
                        },
                        "required": ["distance_km", "type", "label"]
                    },
                    "description": "List of waypoints to suggest"
                }
            },
            "required": ["gpx_id", "waypoints"]
        }
    },
    {
        "name": "manage_annotations",
        "description": (
            "Directly add, remove, update, or list annotations on a prediction. "
            "Use when the user explicitly asks to add/remove/move specific waypoints, "
            "or after the user accepts suggestions. Use 'list' action first to see "
            "existing annotations before modifying."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prediction_id": {
                    "type": "integer",
                    "description": "ID of the prediction to modify"
                },
                "action": {
                    "type": "string",
                    "enum": ["add", "remove", "update", "list"],
                    "description": "Action to perform"
                },
                "annotation": {
                    "type": "object",
                    "description": "Annotation data for add/update actions",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["aid_station", "generic", "water", "checkpoint", "caution"]
                        },
                        "distance_km": {"type": "number"},
                        "label": {"type": "string"},
                        "stop_time_seconds": {"type": "integer"}
                    }
                },
                "annotation_id": {
                    "type": "string",
                    "description": "ID of the annotation for remove/update actions"
                }
            },
            "required": ["prediction_id", "action"]
        }
    },
    {
        "name": "get_route_segments",
        "description": (
            "Get segment-level data for a GPX route to reason about waypoint placement. "
            "Returns per-segment data summarized every ~500m: distance, elevation, grade, "
            "cumulative stats. Use before suggest_waypoints to find strategic points."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "get_equipment_suggestion",
        "description": (
            "Suggest equipment and gear for a trail run based on weather forecast, "
            "terrain analysis, recent weather conditions (trail moisture/mud), and "
            "expected duration. Categories: shoes, clothing layers, rain gear, "
            "headlamp (based on sunrise/sunset vs expected duration), hydration, "
            "sun protection. Use when a runner asks what to wear or bring."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the GPX route"
                },
                "date": {
                    "type": "string",
                    "description": "Planned run date in YYYY-MM-DD format (optional, defaults to today)"
                }
            },
            "required": ["gpx_id"]
        }
    },
    # ========================================================================
    # Training Plan Generator tools
    # ========================================================================
    {
        "name": "get_training_history",
        "description": (
            "Get the user's recent training history as weekly aggregates. "
            "Returns per-week: total volume_km, elevation_m, activity count, avg_pace, "
            "and longest run. Use this to understand current training load and patterns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "weeks": {
                    "type": "integer",
                    "description": "Number of weeks of history to retrieve (default: 8)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_performance_trends",
        "description": (
            "Get performance trend data from historical snapshots. "
            "Returns flat_pace trend, volume trend, and fitness trajectory over time. "
            "Use this to understand if the runner is improving, plateauing, or declining."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "period_type": {
                    "type": "string",
                    "enum": ["weekly", "monthly"],
                    "description": "Period granularity (default: weekly)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of periods to return (default: 12)"
                }
            },
            "required": []
        }
    },
    {
        "name": "get_race_profile",
        "description": (
            "Analyze a target race GPX route in detail. Returns distance, elevation profile, "
            "terrain breakdown, difficulty rating, grade statistics, and estimated finish time. "
            "Use this to understand what the training plan needs to prepare the runner for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "gpx_id": {
                    "type": "integer",
                    "description": "ID of the target race GPX route"
                }
            },
            "required": ["gpx_id"]
        }
    },
    {
        "name": "generate_training_week",
        "description": (
            "Validate and structure ONE training week. Use this ONLY to edit or "
            "replace a single week of an existing plan (e.g. swap a workout, fix "
            "a quality_warnings issue, adjust volume for one week). "
            "Do NOT use this to build a full plan from scratch — call "
            "generate_full_plan instead, which runs the deterministic engine in a "
            "single API call. Building a full plan via repeated generate_training_week "
            "calls will saturate the input-token-per-minute rate limit on long plans. "
            "Pass: week_number, theme, total_km, total_elevation_m, and days array. "
            "Each day needs: day (Monday-Sunday), workout_type, title, distance_km, elevation_m. "
            "Validated weeks are cached and auto-collected by save_training_plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "week_number": {
                    "type": "integer",
                    "description": "Week number in the plan (1, 2, 3...)"
                },
                "theme": {
                    "type": "string",
                    "description": "Week theme, e.g. 'Base building', 'Peak volume', 'Taper'"
                },
                "total_km": {
                    "type": "number",
                    "description": "Target total weekly distance in km"
                },
                "total_elevation_m": {
                    "type": "number",
                    "description": "Target total weekly elevation gain in meters"
                },
                "days": {
                    "type": "array",
                    "description": "Array of daily workouts for this week (5-7 days)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {
                                "type": "string",
                                "enum": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                            },
                            "workout_type": {
                                "type": "string",
                                "enum": ["easy", "tempo", "intervals", "long_run", "hill_repeats", "rest", "cross_train", "recovery", "vert_session", "back_to_back", "race_simulation", "strength"]
                            },
                            "title": {
                                "type": "string",
                                "description": "Short workout title, e.g. '6x hill repeats', 'Long trail run'"
                            },
                            "distance_km": { "type": "number" },
                            "elevation_m": { "type": "number" },
                            "intensity": {
                                "type": "string",
                                "enum": ["easy", "moderate", "hard", "race_pace"]
                            },
                            "notes": { "type": "string" }
                        },
                        "required": ["day", "workout_type", "title", "distance_km", "elevation_m"]
                    }
                },
                "race_date": {
                    "type": "string",
                    "description": "Target race date (YYYY-MM-DD). Provide on the first week call."
                },
                "total_weeks": {
                    "type": "integer",
                    "description": "Total weeks in plan. Provide on the first week call."
                },
                "target_gpx_id": {
                    "type": "integer",
                    "description": "GPX route ID for the target race (if available)"
                },
                "target_race_distance_km": {
                    "type": "number",
                    "description": "Target race distance in km (when no GPX available)"
                }
            },
            "required": ["week_number", "theme", "days"]
        }
    },
    {
        "name": "save_training_plan",
        "description": (
            "Save a complete training plan to the database. Call this after generating "
            "all weeks with generate_training_week. The 'weeks' parameter is optional — "
            "if omitted, the previously validated weeks from generate_training_week are used automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_name": {
                    "type": "string",
                    "description": "Name for the training plan"
                },
                "race_date": {
                    "type": "string",
                    "description": "Target race date in YYYY-MM-DD format (optional)"
                },
                "target_gpx_id": {
                    "type": "integer",
                    "description": "ID of the target race GPX route (optional)"
                },
                "race_description": {
                    "type": "string",
                    "description": "Description of the target race (optional)"
                },
                "weeks": {
                    "type": "array",
                    "items": {
                        "type": "object"
                    },
                    "description": "List of validated week objects from generate_training_week"
                },
                "race_priority": {
                    "type": "string",
                    "enum": ["A", "B", "C"],
                    "description": "Race priority: A (goal race), B (important), C (training race). Optional."
                }
            },
            "required": ["plan_name", "weeks"]
        }
    },
    {
        "name": "generate_full_plan",
        "description": (
            "Generate a complete training plan using the constraint-based plan engine. "
            "PREFERRED over generate_training_week — produces all weeks in one call with "
            "proper periodization, elevation progression, and race-specific workouts. "
            "The engine enforces coaching rules (10% progression, 3:1 recovery modulation, "
            "peak weeks at 100% race D+, long run at 75% race distance). "
            "Returns all weeks ready for save_training_plan. "
            "After calling this, present the plan summary to the user and call save_training_plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "total_weeks": {
                    "type": "integer",
                    "description": "Number of weeks in the plan (compute from today to race date)"
                },
                "race_distance_km": {
                    "type": "number",
                    "description": "Race distance in km"
                },
                "race_elevation_m": {
                    "type": "number",
                    "description": "Race total elevation gain in meters"
                },
                "race_date": {
                    "type": "string",
                    "description": "Race date in YYYY-MM-DD format"
                },
                "athlete_weekly_km": {
                    "type": "number",
                    "description": "Athlete's current average weekly km (from get_training_history)"
                },
                "athlete_weekly_elev": {
                    "type": "number",
                    "description": "Athlete's current average weekly elevation gain in meters"
                },
                "athlete_longest_run_km": {
                    "type": "number",
                    "description": "Athlete's longest recent run in km (from get_training_history)"
                },
                "athlete_category": {
                    "type": "string",
                    "enum": ["cat_1", "cat_2"],
                    "description": "Athlete category (from assess_training_readiness)"
                },
                "long_run_day": {
                    "type": "string",
                    "enum": ["Saturday", "Sunday"],
                    "description": "Day for the weekly long run"
                },
                "rest_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Days the athlete cannot train, e.g. ['Friday']"
                },
                "race_type": {
                    "type": "string",
                    "enum": ["loop", "uphill_only", "downhill_finish"],
                    "description": "Race type — loop (D+ ≈ D-), uphill_only (VK), or downhill_finish. Default: loop"
                },
                "back_to_back": {
                    "type": "boolean",
                    "description": "Enable back-to-back hard sessions (day before long run is hard). For ultra prep."
                },
                "target_gpx_id": {
                    "type": "integer",
                    "description": "Optional GPX route ID — if provided, race profile key_sections are used for workout customization"
                },
                "mountain_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Days the athlete can access trails with significant elevation. "
                        "Elevation-heavy workouts (hill_repeats, vert_session) are placed ONLY "
                        "on these days. Non-mountain days get flat runs. "
                        "Omit or set null if all days have mountain access."
                    )
                },
                "treadmill_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Days the athlete runs on a treadmill. They count as climb-eligible "
                        "(incline) even when not in mountain_days, but never get the "
                        "descent_session; their D+ is capped by treadmill_max_incline_pct."
                    )
                },
                "treadmill_max_incline_pct": {
                    "type": "number",
                    "description": "Treadmill max incline in % (default 10). No decline is assumed."
                },
                "long_long_run_hours": {
                    "type": "number",
                    "description": (
                        "Optional longer long run (hours) every long_long_run_every_weeks "
                        "Build/Peak weeks, e.g. 4 with max_long_run_hours 3. Needs both fields."
                    )
                },
                "long_long_run_every_weeks": {
                    "type": "integer",
                    "description": "Cadence of the long-long run in Build/Peak weeks (e.g. 4)."
                },
                "intensity_distribution": {
                    "type": "string",
                    "enum": ["polarized", "pyramidal"],
                    "description": (
                        "polarized swaps the Build Z3 tempo for short Z4-Z5 VO2 intervals "
                        "(athlete trains mostly Z1-Z2 with quality in Z4-Z5). "
                        "Default: current behaviour (Z3 tempo)."
                    )
                },
                "strength_training_days": {
                    "type": "integer",
                    "description": "Number of strength & conditioning sessions per week (0-3). 0 km, 0 elev."
                },
                "strength_preferred_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Preferred days for strength training, e.g. ['Tuesday', 'Thursday']"
                },
                "overrides": {
                    "type": "object",
                    "description": (
                        "Optional tunable parameter overrides. Use when the user requests "
                        "specific plan adjustments like 'high volume', 'aggressive taper', etc. "
                        "Available keys with defaults and ranges: "
                        "long_run_peak_fraction (0.75, 0.50-0.85), "
                        "peak_volume_fraction (1.30, 1.10-1.60), "
                        "recovery_volume_fraction (0.50, 0.35-0.60), "
                        "taper1_volume_fraction (0.65, 0.45-0.75), "
                        "elev_ramp_factor (0.80, 0.50-1.00), "
                        "base_growth_per_week (0.05, 0.03-0.10), "
                        "build_growth_per_week (0.07, 0.04-0.12). "
                        "Values outside bounds are clamped for safety."
                    )
                },
                "acknowledge_long_run_cap": {
                    "type": "boolean",
                    "description": (
                        "Set to true ONLY after the user has chosen accept_compromise "
                        "in response to a long_run_cap_below_race_target conflict. "
                        "Suppresses the conflict gate and lets the engine clip long runs "
                        "to max_long_run_km. Never set this on the first generation attempt."
                    )
                },
                "force_unrealistic": {
                    "type": "boolean",
                    "description": (
                        "Set to true ONLY after the user has explicitly accepted the "
                        "injury risk in response to a race_not_feasible verdict. "
                        "Suppresses the readiness gate (long-run jump, CTL, weeks). "
                        "Never set this on the first generation attempt — first explain "
                        "the verdict and the alternative races returned by the gate, "
                        "and let the user pick."
                    )
                }
            },
            "required": ["total_weeks", "race_distance_km", "race_elevation_m", "race_date",
                         "athlete_weekly_km", "athlete_weekly_elev", "athlete_longest_run_km",
                         "athlete_category", "long_run_day", "rest_days"]
        }
    },
    # ========================================================================
    # Plan Compliance & Adaptive Coaching tools
    # ========================================================================
    {
        "name": "list_activities",
        "description": (
            "List the runner's individual activities between two dates (default: last 14 days). "
            "Returns activity_id, date, name, km, D+, moving time, avg/max HR (when streams are stored), "
            "is_race and the matched plan day with compliance. Use the activity_id with "
            "get_activity_detail or compare_to_plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start": {"type": "string", "description": "YYYY-MM-DD (default: 14 days ago)"},
                "end": {"type": "string", "description": "YYYY-MM-DD inclusive (default: today)"},
                "type": {"type": "string", "description": "Optional sport type filter, e.g. run, trail_run"}
            },
            "required": []
        }
    },
    {
        "name": "get_activity_detail",
        "description": (
            "Detailed analysis of ONE workout: per-split pace, GAP, HR, cadence, D+/D-, grade; time in "
            "HR zones; HR drift / Pa:HR decoupling (first vs second half); detected climbs and descents "
            "(length, grade, VAM, HR, descent speed); work/recovery block detection for interval sessions. "
            "Treadmill/indoor runs report altitude as unavailable (never flat climbs) and use the planned "
            "incline when a plan day matches. Streams are fetched from Strava on demand and cached. "
            "resolution: 'km' (default), 'segment' (200 m) or 'lap' (detected work/recovery blocks)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer", "description": "Activity id from list_activities"},
                "resolution": {"type": "string", "enum": ["km", "lap", "segment"]}
            },
            "required": ["activity_id"]
        }
    },
    {
        "name": "compare_to_plan",
        "description": (
            "Compare one completed workout with the planned workout of the same day: planned vs done "
            "(km, D+, duration), per-step HR-zone target adherence for structured workouts, and a short verdict."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer", "description": "Activity id from list_activities"}
            },
            "required": ["activity_id"]
        }
    },
    {
        "name": "get_segment_improvement",
        "description": (
            "Improvement index on one stretch of a run: finds earlier runs that covered the same stretch "
            "(GPS within tolerance_m of its start and end, similar length) and compares time, HR and "
            "m_per_beat (grade-adjusted metres per minute per beat above rest). index_pct = today vs the "
            "median of past passes, positive = better. Default stretch: the run's biggest climb. "
            "metric 'eff' (default, fair across HR levels) or 'time'. Needs >= 3 past passes. Fetches "
            "missing GPS tracks from Strava, at most 20 per call: if pending_runs > 0, call again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "activity_id": {"type": "integer", "description": "Activity id from list_activities"},
                "start_km": {"type": "number", "description": "Stretch start, km from the run start"},
                "end_km": {"type": "number", "description": "Stretch end, km from the run start"},
                "metric": {"type": "string", "enum": ["eff", "time"]},
                "tolerance_m": {"type": "number", "description": "Match radius 15-100 m (default 30)"},
                "period_days": {"type": "integer", "description": "Look back this many days (default 365)"}
            },
            "required": ["activity_id"]
        }
    },
    {
        "name": "get_plan_compliance",
        "description": (
            "Get compliance summary for the user's active training plan. "
            "Returns per-week completion rates, missed workouts, volume planned vs actual, "
            "and overall compliance %. Use this to understand how well the runner is "
            "following their plan before suggesting adjustments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "Plan ID (optional, defaults to active plan)"
                }
            },
            "required": []
        }
    },
    {
        "name": "inspect_training_plan",
        "description": (
            "Inspect an entire training plan to get a structured overview before "
            "making changes. Returns per-week summaries: total_km, elevation_m, "
            "long_run distance, number of hard sessions (intervals/tempo/hill_repeats/"
            "race_simulation), number of easy/rest days, and week theme. Also returns "
            "plan-level analysis: volume progression (week-over-week % changes), "
            "elevation progression, intensity distribution, taper assessment, "
            "and training quality warnings (e.g. >10% volume jumps, missing long runs, "
            "intensity in taper weeks, insufficient elevation specificity vs race D+). "
            "Use this BEFORE adjust_training_week to understand the full plan structure "
            "and identify what needs fixing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "Plan ID (optional, defaults to active plan)"
                }
            },
            "required": []
        }
    },
    {
        "name": "adjust_training_week",
        "description": (
            "Modify workouts in a future week of the active training plan. "
            "Use after reviewing compliance to adapt the plan. Only modifies "
            "upcoming weeks — past weeks cannot be changed. Returns the updated "
            "week for user review."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer", "description": "Training plan ID"},
                "week_number": {"type": "integer", "description": "Week number to modify"},
                "days": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {
                                "type": "string",
                                "enum": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                            },
                            "workout_type": {
                                "type": "string",
                                "enum": ["easy", "tempo", "intervals", "long_run", "hill_repeats", "rest", "cross_train", "recovery", "vert_session", "back_to_back", "race_simulation", "strength"]
                            },
                            "title": {"type": "string"},
                            "distance_km": {"type": "number", "description": "Must be 0 for rest/cross_train days"},
                            "elevation_m": {"type": "number", "description": "Elevation gain in meters. Must be 0 for rest/cross_train days"},
                            "duration_min": {"type": "number"},
                            "notes": {"type": "string"},
                            "steps": {
                                "type": "array",
                                "description": "Optional structured workout steps",
                                "items": { "type": "object" }
                            }
                        },
                        "required": ["day"]
                    },
                    "description": "List of day modifications to apply"
                }
            },
            "required": ["plan_id", "week_number", "days"]
        }
    },
    {
        "name": "get_plan_templates",
        "description": (
            "Get available training plan templates for common race types. "
            "Returns pre-built plan skeletons (Trail 30K, 50K, 80K/Ultra, Road Marathon) "
            "with phase structure and weekly workout distribution. "
            "Use one as a starting point and customize based on the runner's fitness."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "template_id": {
                    "type": "string",
                    "description": "Specific template ID to get full details (optional, omit for list)"
                }
            },
            "required": []
        }
    },
    # ========================================================================
    # Season Planning & Race Report tools
    # ========================================================================
    {
        "name": "get_season_overview",
        "description": (
            "Get an overview of all planned races for the season. "
            "Returns races with priorities (A/B/C), countdowns, predicted times, "
            "completion status, and season validation warnings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "generate_race_report",
        "description": (
            "Generate a post-race analysis comparing actual splits to predicted. "
            "Builds per-km pace comparison and rule-based insights about where "
            "time was gained or lost. Marks the plan as completed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "Training plan ID for the completed race"
                },
                "strava_activity_id": {
                    "type": "integer",
                    "description": "Strava activity ID of the race"
                }
            },
            "required": ["plan_id", "strava_activity_id"]
        }
    },
    {
        "name": "get_race_report",
        "description": (
            "Retrieve an existing post-race report for a plan. "
            "Returns split comparison, insights, and actual vs predicted times."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "Training plan ID"
                }
            },
            "required": ["plan_id"]
        }
    },
    # ========================================================================
    # Route-Aware Training tools
    # ========================================================================
    {
        "name": "search_training_routes",
        "description": (
            "Search the user's saved training routes matching workout needs. "
            "Filter by distance range, elevation range, and tags. "
            "Returns matching routes with stats and terrain summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_distance_km": {
                    "type": "number",
                    "description": "Minimum route distance in km"
                },
                "max_distance_km": {
                    "type": "number",
                    "description": "Maximum route distance in km"
                },
                "min_elevation_m": {
                    "type": "number",
                    "description": "Minimum elevation gain in meters"
                },
                "max_elevation_m": {
                    "type": "number",
                    "description": "Maximum elevation gain in meters"
                }
            },
            "required": []
        }
    },
    {
        "name": "generate_training_route",
        "description": (
            "Generate a new training route via OpenRouteService near the user's "
            "training base. Creates a loop route with the foot-hiking profile. "
            "Requires the user to have a training base location set. "
            "Returns the generated route with distance, elevation, and terrain data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_distance_km": {
                    "type": "number",
                    "description": "Target route distance in km (default: 10)"
                },
                "target_elevation_m": {
                    "type": "number",
                    "description": "Target elevation gain in meters (optional)"
                },
                "name": {
                    "type": "string",
                    "description": "Name for the generated route"
                }
            },
            "required": []
        }
    },
    {
        "name": "list_training_locations",
        "description": (
            "List the places the user trains from (name, lat/lon, radius_km, weekdays 0=Mon..6=Sun). "
            "Each weekday belongs to at most one place; plan workouts start from their weekday's place."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "set_training_location_for_day",
        "description": (
            "Set which training location one plan workout uses (overriding its weekday's place) "
            "and re-match its route. Pass location_id null to go back to the weekday's place. "
            "Treadmill days ignore locations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "integer"},
                "week_number": {"type": "integer"},
                "day": {"type": "string", "description": "English day name, e.g. 'Tuesday'"},
                "location_id": {"type": ["integer", "null"], "description": "From list_training_locations"}
            },
            "required": ["plan_id", "week_number", "day"]
        }
    },
    {
        "name": "build_route_workout",
        "description": (
            "Build segment-level workout steps for a saved training route. "
            "Analyzes the route's elevation profile and generates structured steps "
            "with segment references, effort targets, and terrain notes. "
            "Use after finding a route with search_training_routes or generate_training_route."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "route_id": {
                    "type": "integer",
                    "description": "ID of the training route"
                },
                "workout_type": {
                    "type": "string",
                    "enum": ["easy", "tempo", "intervals", "long_run", "hill_repeats",
                             "vert_session", "back_to_back", "race_simulation"],
                    "description": "Type of workout to build (default: long_run)"
                },
                "focus": {
                    "type": "string",
                    "enum": ["climbing", "descending", "endurance"],
                    "description": "Training focus for step generation (default: climbing)"
                }
            },
            "required": ["route_id"]
        }
    },
    {
        "name": "lookup_coaching_knowledge",
        "description": (
            "Look up expert coaching knowledge covering trail running and ultra-endurance "
            "training methodology. Use this when you need detailed guidance on training methodology, "
            "nutrition protocols, periodization, race strategy, recovery, strength training, "
            "or other coaching topics. Returns structured, evidence-based coaching advice "
            "with specific numbers and protocols."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "One or more topic keys to look up. Available topics: "
                        "aerobic_base, intensity_zones, periodization, strength_training, "
                        "uphill_training, recovery, mental_toughness, weekly_structure, "
                        "race_pacing, ultra_strategy, nutrition_racing, nutrition_daily"
                    )
                },
                "query_context": {
                    "type": "string",
                    "description": (
                        "Brief description of the runner's question or situation. "
                        "Helps select the most relevant sections within each topic."
                    )
                }
            },
            "required": ["topics"]
        }
    },
    # ========================================================================
    # Training Preferences tools
    # ========================================================================
    {
        "name": "get_training_preferences",
        "description": (
            "Load the user's saved training preferences (long run day, rest days, "
            "mountain days, strength training, max hours). Returns null if no preferences "
            "saved yet. Call this BEFORE generating a plan to check for existing preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "save_training_preferences",
        "description": (
            "Save or update the user's training preferences. Call after the preference "
            "interview to persist answers for future plans."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "long_run_day": {
                    "type": "string",
                    "description": "Preferred day for the long run"
                },
                "back_to_back": {
                    "type": "boolean",
                    "description": "Enable back-to-back hard session before long run"
                },
                "rest_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Days the athlete cannot train"
                },
                "mountain_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Days the athlete can access trails with significant elevation"
                },
                "max_hours_per_day": {
                    "type": "number",
                    "description": "Maximum training hours per session (0.5-12.0)"
                },
                "strength_training_days": {
                    "type": "integer",
                    "description": "Number of strength sessions per week (0-3)"
                },
                "strength_preferred_days": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Preferred days for strength training"
                },
                "max_weekly_km": {
                    "type": "number",
                    "description": "Maximum weekly km the athlete can sustainably run (10-200)."
                },
                "max_long_run_km": {
                    "type": "number",
                    "description": "Maximum long run distance in km (5-80)."
                },
                "max_long_run_hours": {
                    "type": "number",
                    "description": "Maximum long run duration in hours (0.5-12)."
                },
                "mountain_access_per_week": {
                    "type": "number",
                    "description": (
                        "Weekly mountain access budget. Use 0.5 for 'every other week'. "
                        "Engine prefers this over per_month when set."
                    )
                },
                "mountain_access_per_month": {
                    "type": "integer",
                    "description": "Monthly mountain access budget (alternative to per_week)."
                },
                "max_mountain_elevation_m": {
                    "type": "integer",
                    "description": "Max elevation reachable in a single mountain outing (m D+)."
                },
                "max_mountain_distance_km": {
                    "type": "number",
                    "description": "Max distance in a single mountain outing (km)."
                },
                "sample_mountain_route_id": {
                    "type": "integer",
                    "description": "TrainingRoute id used as the user's reference mountain outing."
                },
                "terrain_profile": {
                    "type": "string",
                    "enum": ["flat_urban", "rolling_hills", "mountain"],
                    "description": (
                        "User's typical training terrain. Setting this also marks "
                        "terrain_profile_source='user' so future inferences won't override it."
                    )
                },
                "pace_zone_method": {
                    "type": "string",
                    "enum": ["physics", "vdot", "riegel"],
                    "description": (
                        "How to derive pace zones. 'physics' (default) uses the "
                        "physics-extracted flat pace; 'vdot' uses Daniels' VDOT from a "
                        "recent race; 'riegel' projects a recent race via Riegel. For "
                        "'vdot'/'riegel' also set pace_zone_race_distance_m and "
                        "pace_zone_race_time_s."
                    )
                },
                "pace_zone_race_distance_m": {
                    "type": "number",
                    "description": "Reference race distance in metres for vdot/riegel zone derivation."
                },
                "pace_zone_race_time_s": {
                    "type": "number",
                    "description": "Reference race finishing time in seconds for vdot/riegel zone derivation."
                },
                "hr_max": {
                    "type": "integer",
                    "description": (
                        "Maximum heart rate in bpm (100-240). Enables HR training zones "
                        "alongside pace. Can be auto-detected from Strava."
                    )
                },
                "hr_rest": {
                    "type": "integer",
                    "description": (
                        "Resting heart rate in bpm (25-120). With hr_max, enables more "
                        "accurate Karvonen (HR-reserve) zones."
                    )
                },
                "lthr": {
                    "type": "integer",
                    "description": (
                        "Lactate-threshold heart rate in bpm (80-230). When known, the "
                        "most accurate anchor for HR zones (Friel %LTHR bands)."
                    )
                }
            },
            "required": []
        }
    },
    {
        "name": "raise_long_run_cap",
        "description": (
            "Update the user's max_long_run_km after they agree to raise the cap "
            "in response to a long_run_cap_below_race_target conflict. Validates "
            "5 < new_km <= 80. After this returns status=updated, re-call "
            "generate_full_plan with the original arguments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "new_km": {
                    "type": "number",
                    "description": "The new max_long_run_km value (5-80)."
                }
            },
            "required": ["new_km"]
        }
    },
    {
        "name": "search_tuneup_races",
        "description": (
            "Find candidate B/C tune-up races near the user's training base that "
            "could substitute a peak long run. Use ONLY after a "
            "long_run_cap_below_race_target conflict and after confirming the "
            "search location with the user. Returns ranked candidates with "
            "fit_score on distance/elevation. If the user has no training_base "
            "set the response will indicate requires_location=true — ask the "
            "user for a location and pass it explicitly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_distance_km": {
                    "type": "number",
                    "description": "Desired race distance (km), typically the race-derived peak long run target."
                },
                "target_elev_m": {
                    "type": "number",
                    "description": "Desired race elevation gain (m). Optional but improves fit scoring."
                },
                "window_start": {
                    "type": "string",
                    "description": "Earliest acceptable race date (YYYY-MM-DD), typically the start of the Build phase."
                },
                "window_end": {
                    "type": "string",
                    "description": "Latest acceptable race date (YYYY-MM-DD), typically the end of the Peak phase (~3 weeks before A-race)."
                },
                "country": {
                    "type": "string",
                    "description": "Optional ISO-2 country code (e.g. 'IT', 'FR') to restrict the search. If omitted, inferred from training_base."
                },
                "max_travel_km": {
                    "type": "number",
                    "description": "Optional override for the search radius (km) around the training base. If omitted, falls back to User.training_travel_radius_km, then to 100. Use this when the user volunteered a different willingness to travel during the chat (e.g. 'I can drive up to 250 km')."
                }
            },
            "required": ["target_distance_km", "window_start", "window_end"]
        }
    },
    {
        "name": "find_race_online",
        "description": (
            "Find a race by name: first in the PaceMind calendar, then on the web "
            "(official pages, calendars, tracedetrail, goandrace). Saves it to the "
            "calendar with every course, the poster and the GPX when found. With "
            "import_gpx=true the course GPX is also copied into the user's routes "
            "and its gpx_id returned, ready for run_prediction / get_race_profile / "
            "generate_full_plan(target_gpx_id). Use it whenever the user names a race "
            "you have no data for, instead of guessing date, distance or D+."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Race name, ideally with the town, e.g. 'Penna Trail Molina di Quosa'"},
                "import_gpx": {"type": "boolean", "description": "Copy each found course GPX into the user's routes. Default false."},
                "refresh": {"type": "boolean", "description": "Search the web even if the race is already in the calendar. Default false."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "start_onboarding_questionnaire",
        "description": (
            "Returns the structured onboarding schema for the training preferences wizard. "
            "Call this when get_training_preferences shows missing required fields "
            "(max_weekly_km, terrain_profile). The frontend renders the wizard automatically; "
            "if the user prefers chat, walk through each step using the returned schema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "preview_capacity",
        "description": (
            "Convert a time budget into expected weekly km, elevation gain, and "
            "long-run distance for the calling user. Use this to answer hypothetical "
            "questions in chat (e.g. 'if I add 1h to my Saturday, how many km?') "
            "or to verify the wizard preview server-side. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "available_hours_per_week": {
                    "type": "number",
                    "description": "Total hours/week available for training."
                },
                "usual_midweek_hours": {
                    "type": "number",
                    "description": "Typical midweek (Mon-Fri) session duration in hours."
                },
                "max_long_run_hours": {
                    "type": "number",
                    "description": "Maximum hours the user wants to spend on a single long run."
                },
                "training_ratio_m_per_km": {
                    "type": "number",
                    "description": (
                        "Target elevation density in m D+ per km. If omitted, defaults "
                        "to a rolling-hills value (30 m/km)."
                    )
                }
            },
            "required": ["available_hours_per_week", "max_long_run_hours"]
        }
    },
    {
        "name": "infer_terrain_profile",
        "description": (
            "Analyze the user's recent Strava activities to infer terrain profile "
            "(flat_urban / rolling_hills / mountain) and elevation density statistics. "
            "Read-only — does not persist anything by itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "lookback_days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 90)."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_route_gpx_link",
        "description": (
            "Get the GPX download path for a saved training route (route_id from a plan day "
            "or the routes list). The user downloads it from the route page or the plan calendar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "route_id": {"type": "integer", "description": "Saved TrainingRoute id."}
            },
            "required": ["route_id"]
        }
    },
    {
        "name": "match_routes_to_plan",
        "description": (
            "Attach a real TrainingRoute to every running day of an existing plan. "
            "Returns counts (matched/approx/unmatched) and the list of unmatched workouts "
            "so you can offer alternatives (generate / upload / downgrade) inline."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plan_id": {
                    "type": "integer",
                    "description": "Saved TrainingPlan id."
                }
            },
            "required": ["plan_id"]
        }
    },
    {
        "name": "assess_training_readiness",
        "description": (
            "Assess the user's training readiness by analyzing their recent Strava history. "
            "Classifies the athlete as Category 1 (needs base building, <400 hrs/year) or "
            "Category 2 (can add specificity, >400 hrs/year), checks for Aerobic Deficiency "
            "Syndrome (ADS) risk, evaluates volume trends, training consistency, and longest "
            "recent run vs target race distance. Returns structured recommendations and "
            "suggested plan templates. Based on established endurance training methodology."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_race_distance_km": {
                    "type": "number",
                    "description": "Target race distance in km (optional, used to assess readiness)"
                },
                "target_race_elevation_m": {
                    "type": "number",
                    "description": "Target race elevation gain in meters (optional, used to assess elevation readiness)"
                }
            },
            "required": []
        }
    },
]
