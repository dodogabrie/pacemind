"""Nutrition estimation handler."""

from typing import Dict, Any
from datetime import datetime

from config.hybrid_config import get_logger
from services.hybrid_prediction_service import HybridPredictionService
from services.weather_service import WeatherService
from services.agent.tool_handlers.validation import _get_gpx_points

logger = get_logger(__name__)


def _carb_examples(grams_per_hour: float) -> list:
    """Give concrete food examples for a target g/h of carbs."""
    examples = []
    if grams_per_hour <= 40:
        examples.append("1 gel (25g) every 30-40 min")
        examples.append("Or: 1 energy bar (30-40g) per hour")
    elif grams_per_hour <= 60:
        examples.append("1 gel (25g) + half a bar (15-20g) every 30 min")
        examples.append("Or: 500ml sports drink (30g) + 1 gel per hour")
    else:
        examples.append("1 gel (25g) every 20-25 min + real food at aid stations")
        examples.append("Mix: gels, bars, banana, rice ball, bread with jam, boiled potatoes with salt")
        examples.append("Alternate sweet and savory to avoid flavor fatigue")
    return examples


def _nutrition_notes(duration_hours: float, temp_c: float) -> str:
    """Generate nutrition advice notes."""
    notes = []

    if duration_hours < 1.0:
        notes.append("Short effort — water only is usually sufficient.")
    elif duration_hours < 2.0:
        notes.append("Moderate effort — a gel or small snack at 45-60 min is sufficient.")
    elif duration_hours < 4.0:
        notes.append("Long effort — eat every 30-45 min. Mix gels with real food.")
    else:
        notes.append("Ultra effort — eat early and consistently. Mix gels, bars, and real food. Practice your nutrition plan in training.")

    if temp_c > 28:
        notes.append("Hot conditions — increase fluid intake by 20-30%. Consider ice/cold fluids. Pre-cool if possible.")
    elif temp_c > 22:
        notes.append("Warm conditions — stay on top of hydration. Don't wait until thirsty.")

    if duration_hours > 3:
        notes.append("Sodium matters — use electrolyte tabs/mix, especially in heat.")

    return " ".join(notes)


def _handle_get_nutrition_estimate(tool_input: Dict, user_id: int) -> Dict:
    """Estimate calorie and hydration needs for a route."""
    gpx_id = tool_input.get('gpx_id')
    if not gpx_id:
        return {'error': 'gpx_id is required'}

    points, bounds, error = _get_gpx_points(gpx_id, user_id)
    if error:
        return error

    weight_kg = tool_input.get('runner_weight_kg', 70)
    date_str = tool_input.get('race_date')
    race_date = datetime.strptime(date_str, "%Y-%m-%d") if date_str else None

    # Get prediction for duration estimate
    prediction_service = HybridPredictionService()
    result = prediction_service.predict(
        user_id=user_id,
        gpx_points=points,
        effort='race',
    )

    total_time_hours = result.get('total_time_seconds', 0) / 3600
    segments = result.get('segments', [])
    total_distance_km = (segments[-1]['distance_m'] + segments[-1]['length_m']) / 1000 if segments else 0
    total_elevation = sum(
        seg.get('length_m', 0) * seg.get('grade', 0)
        for seg in segments if seg.get('grade', 0) > 0
    )

    # Get weather for temperature adjustment
    weather_service = WeatherService()
    weather = weather_service.get_weather_for_route(points, race_date) if race_date else None
    temp_c = weather.get('temperature_c', 15) if weather else 15

    # Calorie estimation
    # Running ~1 kcal/kg/km + climbing bonus (~0.5 kcal/kg per 100m gain)
    cal_per_km = weight_kg * 1.0
    cal_elevation = weight_kg * 0.5 * (total_elevation / 100)
    total_calories = cal_per_km * total_distance_km + cal_elevation
    calories_per_hour = total_calories / total_time_hours if total_time_hours > 0 else 0

    # Recommended intake: 200-300 cal/hr for efforts > 90 min
    recommended_cal_per_hour = min(300, max(200, calories_per_hour * 0.3))

    # Carbohydrate targets (g/h) — primary metric for trail runners
    # Based on duration: <2h: 30-40g/h, 2-4h: 40-60g/h, 4-8h: 60-80g/h, 8h+: 60-90g/h
    if total_time_hours < 2:
        carbs_per_hour = 35
    elif total_time_hours < 4:
        carbs_per_hour = 50
    elif total_time_hours < 8:
        carbs_per_hour = 70
    else:
        carbs_per_hour = 80
    total_carbs = round(carbs_per_hour * total_time_hours)

    # Hydration estimation
    # Base: 400-800ml/hr depending on conditions
    base_fluid_ml_per_hour = 500
    if temp_c > 25:
        base_fluid_ml_per_hour = 700
    elif temp_c > 30:
        base_fluid_ml_per_hour = 800
    elif temp_c < 10:
        base_fluid_ml_per_hour = 400

    total_fluid_ml = base_fluid_ml_per_hour * total_time_hours

    # Electrolytes: ~300-500mg sodium per hour
    sodium_mg_per_hour = 400 if temp_c > 25 else 300
    total_sodium_mg = sodium_mg_per_hour * total_time_hours

    # --- Coaching knowledge enrichments ---

    # 1. Effort-level fueling strategy
    effort_level = tool_input.get('effort', 'race')
    is_high_effort = effort_level in ('race', 'competitive')

    if is_high_effort:
        fueling_strategy = {
            'effort_level': 'high (competitive racing)',
            'primary_fuels': 'Quick-burning, easily digestible carbs: gels, sports drinks, Coke',
            'food_examples': [
                'Energy gels (e.g. GU Roctane)',
                'Sports drink mix',
                'Flat Coke at aid stations',
            ],
            'tip': 'At high heart rates digestion is impaired — stick to simple carbs.',
        }
    else:
        fueling_strategy = {
            'effort_level': 'moderate (conversational pace)',
            'primary_fuels': 'Mix of gels and real food — variety prevents flavor fatigue',
            'food_examples': [
                'Trail mix (nuts, dried fruit)',
                'Half PB&J sandwich',
                'Turkey/avocado wrap',
                'Rice balls (onigiri)',
                'Quesadillas or soup at aid stations',
                'Energy bars',
            ],
            'tip': 'Nibble slowly over miles rather than eating large amounts at once.',
        }

    # Gut training recommendation for long ultras
    if total_time_hours > 5:
        fueling_strategy['gut_training'] = (
            'For efforts over 5 hours, practice eating during long training runs. '
            'Your gut is trainable — start with small amounts and build up. '
            'Failed experiments in training prevent race-day disasters.'
        )

    # 2. Hydration warnings
    #    Source: coaching knowledge base
    hydration_warnings = []

    if total_time_hours > 4 and temp_c > 25:
        hydration_warnings.append({
            'type': 'hyponatremia',
            'severity': 'serious',
            'message': (
                'Long effort in warm conditions — risk of hyponatremia '
                '(overhydration with plain water).'
            ),
            'symptoms': [
                'Weight gain during run',
                'Puffiness in hands/face',
                'Nausea or "sloshy stomach"',
                'Irritability or confusion',
                'Clear urine despite heavy exertion',
            ],
            'prevention': [
                'Do NOT overdrink plain water — drink to thirst',
                'Maintain electrolyte intake (300-500 mg sodium/hour)',
                'Use electrolyte tabs or salted snacks',
                'If symptoms appear: STOP drinking, eat salty food, seek medical help',
            ],
        })

    if temp_c > 30:
        hydration_warnings.append({
            'type': 'dehydration',
            'severity': 'serious',
            'message': (
                'Very hot conditions — high dehydration risk. '
                'Increase fluid and electrolyte intake.'
            ),
            'symptoms': [
                'Dark urine or long time without peeing',
                'Loss of ability to sweat',
                'Dizziness or lightheadedness',
                'Weight loss > 2% of body weight',
            ],
            'prevention': [
                'Consume sports drink with salts + sugars + fluid',
                'Cool off at aid stations (ice, cold water on neck)',
                'Increase sodium to 400-500 mg/hour',
                'Pre-cool if possible before start',
            ],
        })

    # 3. Post-run recovery guidance
    #    Source: coaching knowledge base
    recovery_nutrition = {
        'timing': 'Consume 100-200 calories within 30 minutes post-exercise',
        'ratio': '3:1 or 4:1 carbohydrates to protein',
        'why': (
            'Muscles can rapidly replenish glycogen stores during this window; '
            'missing it can delay recovery by days.'
        ),
        'food_examples': [
            'Hardboiled egg + fruit',
            'Smoothie with protein powder',
            'Recovery drink mix with carbs + protein + electrolytes',
            'Huevos rancheros (eggs, beans, avocado, salsa)',
        ],
        'common_mistake': (
            'Socializing at the finish line and forgetting to eat — '
            'can leave you feeling thrashed for days.'
        ),
    }

    # 4. Plant-based options
    #    Source: coaching knowledge base
    plant_based_options = {
        'race_day_foods': [
            'Rice balls (onigiri) — white rice with miso, wrapped in nori; '
            'cools the body in heat, easy to digest',
            'Chocolate adzuki bars — moist, dense, made from most digestible beans',
            'Dates or date-based energy balls',
            'Trail mix with nuts, seeds, and dried fruit',
        ],
        'pre_race_breakfast': (
            'Quinoa porridge (Incan Quin-Wow!) — quinoa with almond milk, '
            'banana, coconut flakes, cinnamon. Can be prepared the night before.'
        ),
        'recovery': (
            'Minnesota Winter Chili — bulgur wheat + beans for complete protein. '
            'Or a smoothie with plant-based protein powder (pea, hemp, or brown rice).'
        ),
        'note': 'These options work well for all athletes, not just plant-based eaters.',
    }

    return {
        'duration_hours': round(total_time_hours, 1),
        'distance_km': round(total_distance_km, 1),
        'elevation_gain_m': round(total_elevation, 0),
        'temperature_c': temp_c,
        'carbohydrates': {
            'grams_per_hour': carbs_per_hour,
            'total_grams': total_carbs,
            'examples': _carb_examples(carbs_per_hour),
        },
        'calories': {
            'total_burn': round(total_calories),
            'recommended_intake_per_hour': round(recommended_cal_per_hour),
            'total_recommended_intake': round(recommended_cal_per_hour * total_time_hours),
        },
        'hydration': {
            'fluid_ml_per_hour': base_fluid_ml_per_hour,
            'total_fluid_ml': round(total_fluid_ml),
            'total_fluid_liters': round(total_fluid_ml / 1000, 1),
        },
        'electrolytes': {
            'sodium_mg_per_hour': sodium_mg_per_hour,
            'total_sodium_mg': round(total_sodium_mg),
        },
        'notes': _nutrition_notes(total_time_hours, temp_c),
        'fueling_strategy': fueling_strategy,
        'hydration_warnings': hydration_warnings,
        'recovery_nutrition': recovery_nutrition,
        'plant_based_options': plant_based_options,
    }
