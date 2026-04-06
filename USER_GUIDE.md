# Medical Staff Rostering System — User Guide

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [First-Time Setup](#2-first-time-setup)
3. [Running the Application](#3-running-the-application)
4. [Running the Tests](#4-running-the-tests)
5. [VS Code — Run and Debug Configuration](#5-vs-code--run-and-debug-configuration)
6. [VS Code — Running Tests with the Test Explorer](#6-vs-code--running-tests-with-the-test-explorer)
7. [Source Module Reference](#7-source-module-reference)

---

## 1. Project Structure

```
schedule-assistant-medical-sector/
├── main.py                        # Entry point — run this to generate a schedule
├── requirements.txt               # Python dependencies
│
├── staff_configs/                 # One .txt file per staff member
│   ├── anna.txt
│   ├── bob.txt
│   └── ...
├── department_requirements.txt    # Staffing minimums per shift and day type
├── swedish_work_law.txt           # Work-law rules loaded by the solver
│
├── src/                           # Application source code
│   ├── models.py                  # Data classes (Staff, Schedule, ShiftType, …)
│   ├── config_parser.py           # Reads config files → ParsedInputs
│   ├── solver.py                  # OR-Tools CP-SAT constraint solver
│   ├── reporter.py                # Generates a human-readable schedule report
│   └── exporters.py               # Writes .ics and .xlsx output files
│
├── tests/                         # Pytest test suite
│   ├── conftest.py                # Shared fixtures (file paths)
│   ├── fixtures/                  # Minimal config files used by tests
│   │   ├── staff_configs/         # alice.txt, bob.txt, carol.txt
│   │   ├── department.txt
│   │   └── law.txt
│   ├── test_models.py
│   ├── test_config_parser.py
│   ├── test_solver.py
│   ├── test_reporter.py
│   └── test_exporters.py
│
└── output/                        # Created automatically when main.py runs
    ├── <name>.ics                 # One iCalendar file per staff member
    └── schedule_overview.xlsx     # Colour-coded admin overview
```

---

## 2. First-Time Setup

All commands are run from the project root directory.

### Create the virtual environment

```bash
python3 -m venv .venv
```

### Install dependencies

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest
```

### (Optional) Set the Anthropic API key

LLM features (smarter config parsing + narrative report) require a key.
Without it the system falls back to the built-in text parser automatically.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

To make this permanent, add the line to your `~/.bashrc` or `~/.zshrc`.

---

## 3. Running the Application

### Quickstart — next Monday, default output dir

```bash
.venv/bin/python main.py
```

### Specify a start date

The start date must be a Monday.

```bash
.venv/bin/python main.py --start-date 2026-04-06
```

### Specify a custom output directory

```bash
.venv/bin/python main.py --start-date 2026-04-06 --output-dir /tmp/schedule_apr
```

### Disable LLM calls (no API key needed)

Uses the built-in key-value parser and skips the Claude narrative report.

```bash
.venv/bin/python main.py --no-llm
```

### Increase the solver time limit

Default is 120 seconds. Raise it for larger or tightly-constrained problems.

```bash
.venv/bin/python main.py --time-limit 300
```

### All flags together

```bash
.venv/bin/python main.py \
  --start-date 2026-04-06 \
  --output-dir output \
  --no-llm \
  --time-limit 180
```

### What the program outputs

| File | Description |
|------|-------------|
| `output/<name>.ics` | iCalendar file — import into Outlook, Google Calendar, etc. |
| `output/schedule_overview.xlsx` | Colour-coded grid: D=day (blue), E=evening (amber), N=night (purple) |

---

## 4. Running the Tests

### Run the full test suite

```bash
.venv/bin/python -m pytest tests/ -v
```

### Run a single test file

```bash
.venv/bin/python -m pytest tests/test_solver.py -v
.venv/bin/python -m pytest tests/test_models.py -v
.venv/bin/python -m pytest tests/test_config_parser.py -v
.venv/bin/python -m pytest tests/test_reporter.py -v
.venv/bin/python -m pytest tests/test_exporters.py -v
```

### Run a single test by name

```bash
.venv/bin/python -m pytest tests/test_solver.py::test_mandatory_day_off_respected -v
```

### Run tests matching a keyword

```bash
.venv/bin/python -m pytest tests/ -k "night" -v
```

### Stop at the first failure

```bash
.venv/bin/python -m pytest tests/ -x -v
```

### Show a coverage report (install pytest-cov first)

```bash
.venv/bin/pip install pytest-cov
.venv/bin/python -m pytest tests/ --cov=src --cov-report=term-missing
```

### What is and is not tested

| Module | What is tested | What is skipped |
|--------|---------------|-----------------|
| `models.py` | All data classes and their methods | — |
| `config_parser.py` | All helper functions, fallback parser, file reader | `_parse_with_llm` (requires API key) |
| `solver.py` | Feasibility, hard constraints HC-01/HC-05/HC-06, dept minimums, infeasible detection | — |
| `reporter.py` | `_build_schedule_summary` (plain-text section) | `generate_report` / `_call_llm` (requires API key) |
| `exporters.py` | `.ics` event structure, file creation, `.xlsx` sheet names | — |

---

## 5. VS Code — Run and Debug Configuration

Create the file `.vscode/launch.json` in the project root with the content below.
This lets you run or debug any configuration from the Run and Debug panel
(`Ctrl+Shift+D` / `Cmd+Shift+D`) or by pressing `F5`.

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Run: main.py (next Monday, no LLM)",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/main.py",
      "args": ["--no-llm"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal"
    },
    {
      "name": "Run: main.py (custom date, no LLM)",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/main.py",
      "args": ["--start-date", "2026-04-06", "--no-llm"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal"
    },
    {
      "name": "Run: main.py (with LLM)",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/main.py",
      "args": ["--start-date", "2026-04-06"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal",
      "env": {
        "ANTHROPIC_API_KEY": "<your key here>"
      }
    },
    {
      "name": "Test: all tests",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/", "-v"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal"
    },
    {
      "name": "Test: test_solver.py",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/test_solver.py", "-v"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal"
    },
    {
      "name": "Test: test_config_parser.py",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["tests/test_config_parser.py", "-v"],
      "python": "${workspaceFolder}/.venv/bin/python",
      "console": "integratedTerminal"
    }
  ]
}
```

To use this:

1. Open the Run and Debug panel with `Ctrl+Shift+D`
2. Select a configuration from the dropdown at the top
3. Press `F5` to run, or click the green play button

You can set breakpoints in any `.py` file by clicking to the left of the line number. Execution will pause there when running with `F5`.

---

## 6. VS Code — Running Tests with the Test Explorer

The Test Explorer provides a visual tree of all tests with pass/fail status.

### One-time setup

1. Open the Command Palette (`Ctrl+Shift+P`)
2. Run **Python: Select Interpreter**
3. Choose the interpreter at `.venv/bin/python`

VS Code will detect the `pytest` configuration automatically. If it does not,
create `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["tests"],
  "python.testing.unittestEnabled": false
}
```

### Using the Test Explorer

| Action | How |
|--------|-----|
| Open Test Explorer | Click the flask icon in the Activity Bar, or `Ctrl+Shift+P` → **Testing: Focus on Test Explorer View** |
| Run all tests | Click the double-play button at the top of the Test Explorer |
| Run one file | Click the play button next to the file name |
| Run one test | Click the play button next to the test name |
| Debug a test | Right-click a test → **Debug Test** |
| Re-run failed tests | Click the re-run icon (circular arrow with X) |

Green check = passed. Red X = failed. Clicking a failed test shows the error and diff inline.

---

## 7. Source Module Reference

### `src/models.py`

Pure data classes — no I/O, no external dependencies.

| Symbol | What it is |
|--------|-----------|
| `ShiftType` | Enum: `DAY`, `EVENING`, `NIGHT` |
| `Role` | Enum: `NURSE`, `DOCTOR` |
| `Staff` | One staff member with contract and constraints |
| `StaffConstraints` | Hard/soft rules for one person (days off, allowed shifts, …) |
| `StaffPreferences` | Soft preferences (preferred shifts, avoid shifts, …) |
| `DepartmentRequirements` | Minimum staffing per shift type and day type |
| `WorkLawRules` | Swedish work-law numeric limits |
| `ShiftAssignment` | A single (staff, date, shift) assignment |
| `Schedule` | The full result: list of assignments + metadata |
| `ParsedInputs` | Everything the solver needs: staff list + dept reqs + law rules |

### `src/config_parser.py`

Reads `.txt` config files and returns a `ParsedInputs` object.

```
parse_all_inputs(staff_config_dir, dept_req_file, law_file, start_date, use_llm=True)
    → ParsedInputs
```

Set `use_llm=False` to skip the Claude API call and use the built-in
key-value parser. This is the mode used by the test suite.

### `src/solver.py`

Runs the constraint solver and returns a `Schedule` (or `None` if infeasible).

```
build_schedule(inputs, start_date, num_weeks=8, solver_time_limit_s=120)
    → Schedule | None
```

Constraint tiers enforced:
- **Tier 1** — Swedish work law (rest hours, weekly caps, night shift limits)
- **Tier 2** — Department minimum staffing per shift
- **Tier 3** — Personal hard constraints (mandatory/recurring days off, allowed shifts)
- **Soft** — Shift preferences maximised in the objective function

### `src/reporter.py`

Generates a human-readable report from a completed schedule.

```
generate_report(schedule, inputs) → str
```

Calls Claude if `ANTHROPIC_API_KEY` is set; otherwise returns the plain-text
summary produced by `_build_schedule_summary`.

### `src/exporters.py`

Writes output files from a completed schedule.

```
export_ics_files(schedule, inputs, output_dir)   # one .ics per staff member
export_excel(schedule, inputs, output_dir)        # schedule_overview.xlsx
```

Both functions create `output_dir` automatically if it does not exist.
