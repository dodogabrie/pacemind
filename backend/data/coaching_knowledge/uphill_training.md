# Uphill Training for Mountain Athletes

## Key Principles
- Uphill performance is where the greatest speed difference exists between elite and amateur athletes
- Even a few percent improvement in uphill speed translates to several minutes gained over a long climb
- Well over 80% of energy expenditure in skimo is on uphills; over 50% for mountain running
- The biggest limitation to performance comes from overcoming gravity while climbing
- Training should emphasize time on feet going up and down mountains

## Uphill-Specific Training Methods

### Hill Sprints (Anaerobic Capacity / Specific Power)
**What:** Maximum-power 8-10 second sprints uphill with full recovery
**Gradient:** 30-50% grade (steeper = better for strength, but >50% is hard for traction)
**Rest:** 2 min walk down between reps; 3 min between sets
**Volume:** Start 6-8 reps, add max 2 reps/week
**When:** Base Period onward, 1x/week
**Effect:** Neurological initially (brain learns to recruit FT fibers) → improved power, stride length, economy
**Note:** Most endurance athletes struggle — if it feels ineffective, you need it MORE (you're only using ST fibers)

### Hill Bounding (Specific Strength)
**What:** Exaggerated long strides uphill with more airborne time and lower tempo than sprints
**Use:** Specific strength training; can be done with poles to simulate skiing
**Duration:** 8-10 seconds at maximum power
**Progression:** Same as Hill Sprints — 6-8 reps, add 2/week

### Outdoor Muscular Endurance (ME) on Hills
**Method 1 — Steep Z3 Grinding:**
- Find 20-50% grade hill
- Run or power-hike straight up the fall line
- Maintain low-level leg burn for 8-40 min continuous
- Start: 2x 8-10 min with 5-min recovery
- Build to: 40 min steady uphill grinding
- A preferred ME method among elite mountain runners

**Method 2 — Bounding Intervals:**
- Short explosive bounds up steep trail
- Start: 10x10 sec bounding, walk-down recovery
- Progress: 15x15 sec with 1 min recovery; then 20x20 sec with 2 min
- Between bounds: walk/run back down until legs recover, then repeat

**Method 3 — Weighted Uphill:**
- Add 10-15% body weight in pack
- Use either Z3 grinding or bounding on available terrain
- Useful when steep hills aren't available
- Fire stairs in tall buildings work well

### Steep Uphill Intervals (Z3-Z4)
**Zone 3 Threshold Intervals:**
- 20-60 min total work, done as intervals of 3-20 min
- Work:rest ratio 3:1 to 4:1
- New athletes: start 3x6 min with 2 min rest
- Advanced: work up to 3x20 min or 2x30 min
- Strong muscular endurance effect

**Zone 4 Aerobic Power Intervals:**
- Total work volume 15-30 min
- Work periods 30 sec to 8 min
- Work:rest ratio 1:1
- Must be at 90-95% max HR
- Best done on uphills
- If legs fail before breathing, need more ME work first

**30/30s (excellent Z4 introduction):**
- 30 sec hard, 30 sec easy — but only slow enough for 5-7 bpm HR drop
- Build effort so you hit Z4 by second rep
- Start: 2x6 min of 30/30s with few min rest
- Progress: 2x8, 2x10, 2x15, then 1x20 min
- 30 min total is tough but achievable goal

### High-Tempo/High-Resistance Intervals
**What:** Alternating stride types on steep uphills
**How:** 2 min high-tempo/high-HR running → 2 min active rest → 2 min long strides (bounding)
**Repeat:** Until pace and HR drop off
**Effect:** Combines Z4 aerobic power with ME training

## Vertical Training Volume

### Weekly Vertical Guidelines
- If new to mountain sports: start with 1/3 to 1/2 of goal event's total vertical in week 1
- Plan to hit goal event's total vertical in at least 2 late Base Period weeks
- Big vertical weeks should correspond to longer distance weeks
- Cut vertical 40-60% during recovery weeks
- Track vertical alongside time and distance — vertical is a primary training load metric

### Recording Training for Mountain Sports
- Running: time + vertical meters + distance
- Skiing: time + vertical meters
- Technical difficulty scale:
  - Tech 1: On piste ski or good track/easy trail
  - Tech 2: Off piste or rough track/medium trail
  - Tech 3: Off piste, some scrambling/off-trail scrambling
  - Tech 4: Climbing

## Downhill Training

### Why It Matters
- Downhill running requires different strength and agility than uphill
- Motor patterns for downhill are learned through repetition — no shortcut
- Late-race stride length decrease is one of the most powerful predictors of results
- Downhill eccentric loading contributes to DOMS that can last days

### How to Train It
- Insert short (1-2 min) high-speed downhill reps into weekly easy workouts
- Increase number and duration over weeks
- Count downhill time in total workout time (don't dismiss because HR is low)
- Downhills provide valuable strengthening effect
- Muscular endurance training significantly improves ability to handle downhill stress

## Movement Economy on Varied Terrain
- Running on flat surfaces hardwires nervous system for flat-surface motor patterns
- Switching to rough terrain/downhills forces slow, inefficient conscious control
- Must run a lot of downhills and rough terrain to build the motor "engram library"
- "You will not learn to play Chopin by practicing Chopsticks"
- Technical proficiency is time-consuming but there is no other way
- Long workouts at Z1-Z2 on varied terrain also improve technique through sheer volume of practice

## Elevation Density Guidelines for Training Plans

**IMPORTANT:** Distance in training plans always means TOTAL distance (the full loop/out-and-back),
not just the uphill portion. A "10km run with 500m D+" means a 10km loop that includes 500m of
climbing AND the corresponding descent.

### The Race-Ratio Principle
Training elevation density should match the RACE's own terrain profile. But first, distinguish
between race types:

**Loop / out-and-back races** (D+ ≈ D-):
- Race ratio = D+ / total_distance. E.g. 50km with 2,877m D+ and 2,877m D- → 58m/km
- Training loops naturally have matching D+/D-, so use race ratio directly
- Training runs should target the same D+/km as the race

**Uphill-only races (VK, point-to-point uphill)** (D+ >> D-):
- Race ratio is misleading: 5km VK with 1,000m D+ = 200m/km
- But you CANNOT train at 200m/km on loops — you always descend back
- Training ratio = D+ / (race_distance × 2). E.g. VK → 1,000m / 10km = 100m/km on loops
- Alternative: treadmill at steep incline, or pure hill repeats where you drive/cable car up

Apply the TRAINING ratio (not race ratio) to workouts:
- Easy runs: at or slightly below training ratio
- Long runs: at training ratio (this IS the key specificity workout)
- Hill repeats / vert sessions: can exceed training ratio by 20-30% to build specific climbing strength
- Recovery runs: well below training ratio (flat is fine)

### Race Profile Analysis (before building any plan)

**If a target GPX route exists:** ALWAYS call `get_race_profile` first. It returns `key_sections`
identifying the race's hardest climbs and descents with exact km, distance, elevation, grade,
and training notes. Use these to design race-specific workouts:
- **steep_climb** sections: design hill repeat workouts that match the gradient and duration
- **long_climb** sections: design Z3 muscular endurance sessions at similar gradient
- **steep_descent** sections: prescribe downhill technique work and eccentric strength training
- **Race type** (`loop` vs `uphill_only` vs `downhill_finish`): determines training ratio calculation

**If NO GPX exists (user describes race verbally):** Calculate the ratio from stated numbers:
- User says "50km with 3500m D+" → race ratio = 3500/50 = 70m/km
- Assume a **loop** race (D+ ≈ D-) unless the user specifies VK or point-to-point
- Apply the training ratio = 70m/km to all training workouts
- Without key sections data, assume the race has a mix of steep climbs and sustained grinding
- Design workouts covering both: steep hill repeats (2-3km at 12-15%) AND long Z3 climbs (5-8km at 7-10%)
- Mention to the user: "Upload the race GPX for more specific workout targeting"

Design 2-3 workouts per week that simulate race-like demands.
The athlete should recognize the race-day effort because they've trained it.

### Difficulty Scale Reference
- **20-40m D+/km**: Normal hilly — accessible everywhere
- **40-60m D+/km**: Mountain training — needs real mountain access
- **60-80m D+/km**: Very demanding — significant physical toll, key workout
- **80-100m D+/km**: Extreme mountain — brutal, only as peak workout with recovery around it
- **>100m D+/km**: VK-level — race-only steepness, not regular training loops

## Decision Rules for the Agent
- IF athlete's goal race has significant climbing (>100m/km) THEN prioritize uphill-specific training
- IF athlete reports legs failing before breathing on uphills THEN prescribe ME work (steep Z3 grinding or gym-based ME)
- IF athlete has limited hill access THEN use weighted pack on moderate terrain or fire stairs, or gym-based ME
- IF athlete is Cat 1 THEN Hill Sprints 1x/week + Z1-Z2 volume; avoid Z3/Z4 uphill intervals until base is sufficient
- IF athlete is Cat 2 with good base THEN can use the high-tempo/high-resistance interval method
- IF athlete reports severe DOMS from downhills THEN increase downhill training volume gradually and add eccentric ME work
- IF event has technical terrain THEN prescribe specific practice on similar terrain — no substitute for hours on rough ground
