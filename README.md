# Medical Staff Rostering System — Med-3

A constraint-based scheduling tool for hospital ward personnel. Given plain-text configuration files for each staff member, a department requirements file, and Swedish work law rules, it automatically generates a law-compliant 8-week shift schedule, exports it as individual calendar files and an admin Excel overview, and produces a human-readable narrative report.

---

## AI tooling

This project was designed and implemented with **Claude Sonnet 4.6** (Anthropic).
The same model is used at runtime for two tasks:
- **Parsing stage** — reading natural-language staff config files and extracting structured scheduling constraints as JSON.
- **Reporting stage** — analysing the completed schedule and producing a narrative explanation of trade-offs and compliance status.

---

## Project structure

```
schedule-assistant-medical-sector/
│
├── main.py                        # Entry point — orchestrates all four pipeline stages
├── requirements.txt               # Python dependencies (OR-Tools, Anthropic SDK, openpyxl, icalendar)
│
├── swedish_work_law.txt           # Tier 1 rules — Arbetstidslagen (1982:673) + Arbetsmiljöverket
├── department_requirements.txt    # Tier 2 rules — Med-3 shift minimums and operational policy
│
├── staff_configs/                 # Tier 3 — one plain-text file per staff member
│   ├── maja.txt                   # Nurse,  100 %
│   ├── pelle.txt                  # Nurse,   80 %
│   ├── kalle.txt                  # Nurse,  100 %
│   ├── gudrun.txt                 # Nurse,   60 %  (day shifts only)
│   ├── clas.txt                   # Nurse,  100 %
│   ├── sofia.txt                  # Nurse,   80 %  (no nights — medical restriction)
│   ├── anna.txt                   # Nurse,  100 %
│   ├── klara.txt                  # Nurse,   75 %
│   ├── nora.txt                   # Doctor, 100 %  (clinical lead, day shifts only)
│   ├── desdemona.txt              # Doctor, 100 %  (no Fridays — research day)
│   ├── karin.txt                  # Doctor, 100 %  (2-week vacation in planning window)
│   └── melvin.txt                 # Doctor, 100 %  (ST-läkare / specialist trainee)
│
├── src/                           # Python source package
│   ├── __init__.py
│   ├── models.py                  # Data classes shared across all modules
│   ├── config_parser.py           # Stage 1 — reads files, calls Claude, returns ParsedInputs
│   ├── solver.py                  # Stage 2 — OR-Tools CP-SAT constraint solver
│   ├── reporter.py                # Stage 3 — Claude narrative report + plain-text summary
│   └── exporters.py               # Stage 4 — writes .ics calendar files and .xlsx overview
│
└── output/                        # Created at runtime
    ├── <name>.ics                 # One calendar file per staff member
    ├── schedule_overview.xlsx     # Colour-coded admin grid
    └── (report printed to stdout)
```

---

## Quick start

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key (optional — omit to run without LLM features)
export ANTHROPIC_API_KEY=your_key_here

# Generate schedule starting the next Monday
python3 main.py

# Or specify a start date explicitly
python3 main.py --start-date 2026-04-06

# Run without any Claude API calls (direct text parser, no narrative report)
python3 main.py --no-llm
```
