# Code Description — Medical Staff Rostering System

This document explains what each file in the `src/` package does and how the pieces connect. The system is a four-stage pipeline: **parse → solve → report → export**.

---

## Pipeline overview

```
Input files (plain text)
        │
        ▼
[1] config_parser.py  ──► ParsedInputs  (Staff list + Dept requirements + Law rules)
        │
        ▼
[2] solver.py         ──► Schedule      (list of ShiftAssignment objects)
        │
        ▼
[3] reporter.py       ──► Narrative text (printed to stdout)
        │
        ▼
[4] exporters.py      ──► .ics files + .xlsx file  (written to output/)
```

Each stage is a plain function (not a class) because it performs one job and returns a result — it does not hold internal state between calls.

---

## `src/models.py` — shared data classes

This file defines every data structure used across the project. Nothing in this file does computation — it only describes what data looks like. All other modules import from here.

### Key classes

**`ShiftType`** (Enum)
A fixed set of the three shift types: `DAY`, `EVENING`, `NIGHT`. Using an Enum instead of plain strings means a typo like `"nigth"` is caught immediately as an error rather than silently producing wrong results.

**`Role`** (Enum)
Either `NURSE` or `DOCTOR`. Used to separate staffing requirements and constraint sets.

**`StaffPreferences`** (dataclass)
Holds soft preferences for one staff member — things the scheduler will *try* to honour but cannot guarantee:
- `preferred_shifts` / `avoid_shifts` — which shift types to aim for or avoid
- `preferred_days_off` — weekdays the person would like free (0=Monday)
- `max_night_shifts_per_week` — soft weekly night cap
- `prefer_consecutive_days_off` — if True, the solver penalises scattered rest days

**`StaffConstraints`** (dataclass)
Holds both hard needs and soft preferences for one staff member:
- `mandatory_days_off` — specific dates that must be free (hard)
- `recurring_days_off` — weekdays that are always off (hard), e.g. every Sunday
- `allowed_shifts` — if set, only those shift types are ever scheduled (hard medical/contractual restriction)
- `max_weekly_shifts` — ceiling from the employment contract (hard)
- `preferences` — the `StaffPreferences` object above (soft)

**`Staff`** (dataclass)
One staff member: name, role, contract percentage, and their `StaffConstraints`. Has two `@property` helpers (`target_shifts_per_week`, `max_shifts_per_week`) that compute derived values so no other module has to repeat the formula.

**`ShiftAssignment`** (dataclass)
A single solved assignment: one staff member, one date, one shift type. The solver produces a list of these.

**`Schedule`** (dataclass)
The complete solved schedule: a list of `ShiftAssignment` objects plus metadata (start date, number of weeks, solver status, broken preferences). Has helper methods to filter assignments by staff name or by date.

**`DepartmentRequirements`** (dataclass)
Minimum headcounts for each combination of shift type (day/evening/night) and day type (weekday/weekend). These become hard constraints in the solver.

**`WorkLawRules`** (dataclass)
Numeric limits derived from Arbetstidslagen. The solver reads these values rather than hardcoding numbers, so they can be changed in one place.

**`ParsedInputs`** (dataclass)
A bundle of the three things produced by `config_parser.py` and consumed by `solver.py`: the staff list, department requirements, and law rules.

---

## `src/config_parser.py` — Stage 1: parsing

**What it does:** reads all input text files and converts their natural-language content into `ParsedInputs` — the structured Python objects the solver understands.

### Entry point

```python
parse_all_inputs(staff_config_dir, dept_req_file, law_file, start_date, use_llm)
```

Reads every `.txt` file in `staff_configs/`, plus the two department/law files. If `use_llm=True` and an API key is set, it calls Claude. Otherwise it falls back to the built-in text parser.

### LLM path (`_parse_with_llm`)

All file contents are concatenated into a single message and sent to `claude-sonnet-4-6` with a carefully structured system prompt. The system prompt defines an exact JSON schema and instructs the model to convert natural-language date references ("every Friday", "weeks 3-4") into ISO-format dates relative to the provided schedule start date. The returned JSON is then passed to `_build_parsed_inputs` which converts it into Python model objects.

### Fallback text parser (`_parse_with_fallback`)

Reads each staff config file line by line, looking for lines in the format `Key: Value`. The `_extract_kv` helper builds a dictionary from these. Specific helpers then convert each field:
- `_parse_contract_pct` — finds a percentage like `80%` and converts it to `0.8`
- `_parse_dates` — finds all `YYYY-MM-DD` patterns
- `_parse_weekdays` — finds weekday names like "Sunday" and maps them to integers
- `_parse_allowed_shifts` / `_parse_shift_list` — finds the words "day", "evening", "night"

The fallback is less capable than the LLM path (it cannot interpret "every other Tuesday") but works without an API key and is reliable for well-structured config files.

---

## `src/solver.py` — Stage 2: constraint solving

**What it does:** uses Google OR-Tools CP-SAT to find a shift schedule that satisfies all hard constraints and maximises soft preferences.

### How CP-SAT works (briefly)

CP-SAT is a *constraint programming* solver. You describe the problem as variables and constraints, set an objective to minimise, and call `solver.Solve()`. It searches the space of all possible assignments and finds one that satisfies every hard constraint while achieving the best possible objective score.

### Decision variables

```python
shifts[(staff_index, day_index, shift_index)] = BoolVar
```

One Boolean variable per (staff member, day, shift type) — `1` if that person works that shift, `0` otherwise. With 12 staff, 56 days, and 3 shift types, this is 12 × 56 × 3 = 2,016 variables. This is small for OR-Tools.

### Hard constraints — Tier 1 (law)

| Code  | Rule | Implementation |
|-------|------|----------------|
| HC-01 | At most 1 shift per person per day | `AddAtMostOne` over the three shift vars for each (person, day) |
| HC-02 | Evening(d) → Day(d+1) forbidden | `shifts[evening,d] + shifts[day,d+1] <= 1` |
| HC-03 | Night(d) → Day(d+1) forbidden | `shifts[night,d] + shifts[day,d+1] <= 1` |
| HC-04 | Night(d) → Evening(d+1) forbidden | `shifts[night,d] + shifts[evening,d+1] <= 1` |
| HC-05 | Max 5 shifts per 7-day week | Sum over week <= 5 |
| HC-06 | No 6 consecutive working days | Sum over any 6-day window <= 5 |
| HC-07 | Max 8 night shifts per 4-week block | Sum of night vars per 28-day block <= 8 |

HC-02 through HC-04 enforce the 11-hour minimum rest rule from Arbetstidslagen §13. They work because the sum of two Boolean variables is `<= 1` only when at most one of them is `1` — i.e. the solver cannot assign both.

### Hard constraints — Tier 2 (operational)

For each (day, shift type) combination, the sum of scheduled nurses must be >= the minimum required, and likewise for doctors. Weekends and public holidays use the weekend minimum values from `DepartmentRequirements`.

### Hard constraints — Tier 3 (personal)

- **Mandatory days off:** set the three shift variables for that (person, day) to `0`.
- **Recurring weekday off:** same, but applied to every matching weekday in the 56-day horizon.
- **Allowed shifts:** for each forbidden shift type, all 56 day-variables for that shift are set to `0`.
- **Weekly contract cap:** sum of shifts in each 7-day week <= `max_weekly_shifts`.

### Soft constraints — objective function

The solver minimises a weighted sum. Lower is better:

| Term | Weight | Effect |
|------|--------|--------|
| Avoid-shift penalty | +10 per shift | Strongly discourages scheduling on avoided shift types |
| Preferred-day-off penalty | +4 per shift | Discourages working on preferred rest days |
| Contract fill bonus | −6 per shift | Pulls the solver to schedule as many shifts as possible up to the contract cap |
| Preferred-shift bonus | −4 per shift | Rewards scheduling on preferred shift types |
| Excess night shifts | +15 per excess night above soft weekly limit | Discourages over-assigning nights |
| Isolated day-off penalty | +3 per isolated rest day | For staff who prefer consecutive days off, penalises a lone off-day surrounded by working days |

The contract fill bonus (−6) is larger in magnitude than the avoid-shift penalty (+10) divided by the number of available alternatives, which means the solver will reluctantly schedule someone on an avoided shift rather than leave a contract slot empty if no preferred shifts are available.

### After solving

The solver iterates over all variables, collects the ones set to `1`, and builds `ShiftAssignment` objects. It simultaneously records any cases where a scheduled shift conflicts with a soft preference, which are stored in `Schedule.infeasible_preferences` for the reporting stage.

---

## `src/reporter.py` — Stage 3: reporting

**What it does:** produces a human-readable explanation of the schedule.

### `_build_schedule_summary`

Always runs (no API required). Formats the schedule into structured plain text:
- Per-staff overview: total shifts, day/evening/night counts, week-by-week grid using letters (`D`, `E`, `N`, `.` for off)
- Daily staffing table: how many nurses and doctors are on each shift each day, with a `⚠ BELOW MIN` flag if minimums are not met
- List of all broken soft preferences

### `_call_llm` (LLM path)

Sends the plain-text summary to `claude-sonnet-4-6` with a system prompt that instructs the model to produce a structured narrative report with five sections: executive summary, compliance confirmation, coverage analysis, preference trade-offs, and recommendations. The LLM output is returned with the raw summary appended as an appendix.

If the API call fails, `generate_report` catches the exception and returns the plain-text summary directly.

---

## `src/exporters.py` — Stage 4: file export

**What it does:** writes the solved schedule to files.

### `.ics` export (`export_ics_files`)

Uses the `icalendar` library. For each staff member, creates a `Calendar` object and adds one `Event` per shift assignment. Each event has:
- `DTSTART` / `DTEND` — datetime objects in the `Europe/Stockholm` timezone
- `SUMMARY` — shift type and ward name
- `DESCRIPTION` — staff name, shift hours, ward details
- `LOCATION` — ward name

Night shifts are handled specially: their end time (`07:00`) falls on the *next calendar day*, so `timedelta(days=1)` is added to the end date.

### `.xlsx` export (`export_excel`)

Uses `openpyxl`. Builds a grid workbook:
- **Row 1** — week number labels (W01 … W08)
- **Row 2** — date headers (Mon dd/mm), with weekends shaded differently
- **Rows 3+** — one row per staff member, one column per day
  - `D` in light blue — day shift
  - `E` in amber — evening shift
  - `N` in purple with white text — night shift
  - Empty grey cell — day off
- **Rightmost column** — `scheduled/target` shifts, red if more than 2 below target
- **Second sheet** — a colour legend

---

## `main.py` — entry point and orchestration

Ties the four stages together. Responsibilities:
1. Parses command-line arguments (`--start-date`, `--output-dir`, `--no-llm`, `--time-limit`)
2. Calculates the schedule start date (defaults to the next Monday)
3. Calls each stage in sequence, printing progress messages
4. Handles the failure case (infeasible solver) with a clear diagnostic message
5. Exits with code `0` on success, `1` on error

The `--no-llm` flag runs the complete pipeline without any API calls: the fallback text parser handles Stage 1, the solver runs unchanged in Stage 2, and Stage 3 returns the plain-text summary only.

---

## Input file format — staff configs

Each file in `staff_configs/` follows a human-readable form structure:

```
Key:   Value
```

The LLM parser reads these as free-form prose. The fallback parser requires values on single lines after a colon. The most important fields the system looks for:

| Field | Hard or soft | Example value |
|-------|-------------|---------------|
| `Name` | — | `Maja Lindqvist` |
| `Role` | — | `Nurse` |
| `Contract` | — | `80%` |
| `Max shifts per week` | Hard | `4` |
| `Allowed shifts` | Hard | `Day only` |
| `Mandatory days off` | Hard | `2026-04-22` |
| `Recurring unavailability` | Hard | `Sunday` |
| `Preferred shifts` | Soft | `Evening, Night` |
| `Avoid shifts` | Soft | `Night` |
| `Preferred days off` | Soft | `Friday, Saturday` |
| `Max night shifts per week` | Soft | `2` |
| `Consecutive days off` | Soft | `Maximise` |
