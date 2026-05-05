#!/usr/bin/env python3
"""
Medical Staff Rostering System — Main Entry Point
==================================================

Default mode is **manual-LLM**: prompts are written to files in the output
directory and the program waits for you to paste responses back. This lets
you use any LLM (ChatGPT, Gemini, local model, etc.) and is the same path
the notebook uses.

Usage:
    python main.py                         # manual-LLM (default)
    python main.py --start-date 2026-04-06
    python main.py --start-date 2026-04-06 --output-dir my_output
    python main.py --api                   # call the Anthropic API directly
    python main.py --no-llm                # text-parser fallback, no report

Environment variable required only for --api:
    ANTHROPIC_API_KEY=<your key>
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

NUM_WEEKS = 4

BASE_DIR = Path(__file__).parent
STAFF_DIR = BASE_DIR / "staff_configs"
DEPT_FILE = BASE_DIR / "department_requirements.txt"
LAW_FILE = BASE_DIR / "swedish_work_law.txt"


def next_monday(from_date: date | None = None) -> date:
    d = from_date or date.today()
    days_ahead = (7 - d.weekday()) % 7
    return d + timedelta(days=days_ahead or 7)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Medical Staff Rostering System — generates an 8-week schedule."
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help="First day of the schedule (must be a Monday). Defaults to the next Monday.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        metavar="DIR",
        help="Directory where .ics and .xlsx files are written (default: ./output).",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--api",
        action="store_true",
        help="Call the Anthropic API directly (requires ANTHROPIC_API_KEY).",
    )
    mode_group.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM entirely. Uses built-in text parser and skips the narrative report.",
    )
    parser.add_argument(
        "--time-limit",
        type=int,
        default=120,
        metavar="SECONDS",
        help="Maximum solver time in seconds (default: 120).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Determine schedule start date
    # ------------------------------------------------------------------
    if args.start_date:
        try:
            start_date = date.fromisoformat(args.start_date)
        except ValueError:
            print(f"ERROR: invalid date format '{args.start_date}' — use YYYY-MM-DD.")
            return 1
        if start_date.weekday() != 0:
            print(f"WARNING: {start_date} is not a Monday "
                  f"({start_date.strftime('%A')}). Schedules conventionally start on Monday.")
    else:
        start_date = next_monday()

    end_date = start_date + timedelta(weeks=NUM_WEEKS) - timedelta(days=1)
    print(f"\n{'='*60}")
    print(f"  Medical Staff Rostering System")
    print(f"  Department: Medicin Avdelning 3 (Med-3)")
    print(f"  Period:  {start_date}  →  {end_date}  ({NUM_WEEKS} weeks)")
    print(f"{'='*60}\n")

    # ------------------------------------------------------------------
    # Parse inputs
    # ------------------------------------------------------------------
    from src.config_parser import parse_all_inputs

    print("[1/4] Parsing configuration files...")
    use_llm = args.api
    manual_llm = not args.api and not args.no_llm
    if use_llm and not __import__("os").environ.get("ANTHROPIC_API_KEY"):
        print("      ERROR: --api requires ANTHROPIC_API_KEY to be set.")
        return 1
    mode_label = "manual-LLM" if manual_llm else ("Anthropic API" if use_llm else "text parser")
    print(f"      Mode: {mode_label}")

    output_dir = Path(args.output_dir)

    inputs = parse_all_inputs(
        staff_config_dir=STAFF_DIR,
        dept_req_file=DEPT_FILE,
        law_file=LAW_FILE,
        start_date=start_date,
        use_llm=use_llm,
        manual_llm=manual_llm,
        output_dir=output_dir,
    )

    print(f"      Loaded {len(inputs.staff)} staff members:")
    for staff in inputs.staff:
        print(f"        • {staff.name:<22} {staff.role.value:<8} "
              f"{int(staff.contract_pct*100):>3}%  "
              f"max {staff.constraints.max_weekly_shifts} shifts/week")

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    from src.solver import build_schedule

    print(f"\n[2/4] Running constraint solver (time limit: {args.time_limit}s)...")
    schedule = build_schedule(
        inputs=inputs,
        start_date=start_date,
        num_weeks=NUM_WEEKS,
        solver_time_limit_s=args.time_limit,
    )

    if schedule is None:
        print("\nERROR: The solver could not find a feasible schedule.")
        print("       Possible causes:")
        print("       • Too many simultaneous mandatory days off")
        print("       • Staffing minimums cannot be met with available staff")
        print("       • Contract constraints conflict with law constraints")
        print("       Review staff config files and department_requirements.txt.")
        return 1

    total_assignments = len(schedule.assignments)
    broken = len(schedule.infeasible_preferences)
    print(f"      Scheduled {total_assignments} shifts across {NUM_WEEKS} weeks.")
    print(f"      Broken soft preferences: {broken}")

    # ------------------------------------------------------------------
    # Generate report
    # ------------------------------------------------------------------
    from src.reporter import generate_report

    print("\n[3/4] Generating schedule report...")
    report = generate_report(schedule, inputs, manual_llm=manual_llm, output_dir=output_dir)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)

    # ------------------------------------------------------------------
    # Export outputs
    # ------------------------------------------------------------------
    from src.exporters import export_excel, export_ics_files

    print(f"\n[4/4] Exporting files to {output_dir}/...")

    export_ics_files(schedule, inputs, output_dir)
    export_excel(schedule, inputs, output_dir)

    print(f"\nDone. Outputs written to: {output_dir.resolve()}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
