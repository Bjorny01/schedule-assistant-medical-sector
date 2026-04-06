"""
LLM reporting layer for the Medical Staff Rostering System.

Sends the completed schedule to Claude and receives a human-readable
narrative explaining trade-offs, broken preferences, and compliance status.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from .models import ParsedInputs, Role, Schedule, ShiftType, Staff

SHIFT_SYMBOLS = {
    ShiftType.DAY: "D",
    ShiftType.EVENING: "E",
    ShiftType.NIGHT: "N",
}


def generate_report(schedule: Schedule, inputs: ParsedInputs) -> str:
    """
    Call Claude to produce a narrative schedule report.

    Falls back to a plain-text summary if the API call fails.
    """
    summary_text = _build_schedule_summary(schedule, inputs)

    try:
        return _call_llm(summary_text, schedule, inputs)
    except Exception as exc:
        print(f"[reporter] LLM report failed ({exc}), using plain summary.")
        return summary_text


# ---------------------------------------------------------------------------
# Plain-text summary (used as LLM input and as fallback)
# ---------------------------------------------------------------------------

def _build_schedule_summary(schedule: Schedule, inputs: ParsedInputs) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("SCHEDULE SUMMARY")
    lines.append(f"Department:     {inputs.dept_requirements.department_name}")
    lines.append(f"Planning period:{schedule.start_date}  to  "
                 f"{schedule.start_date + timedelta(weeks=schedule.num_weeks) - timedelta(days=1)}")
    lines.append(f"Weeks:          {schedule.num_weeks}")
    lines.append(f"Solver status:  {schedule.solver_status}")
    lines.append("=" * 70)

    # Per-staff summary
    lines.append("\nPER-STAFF OVERVIEW")
    lines.append("-" * 70)

    for staff in inputs.staff:
        assignments = schedule.get_staff_assignments(staff.name)
        total = len(assignments)
        target = round(staff.target_shifts_per_week * schedule.num_weeks)
        day_c = sum(1 for a in assignments if a.shift_type == ShiftType.DAY)
        eve_c = sum(1 for a in assignments if a.shift_type == ShiftType.EVENING)
        ngt_c = sum(1 for a in assignments if a.shift_type == ShiftType.NIGHT)

        lines.append(
            f"\n{staff.name} ({staff.role.value}, {int(staff.contract_pct*100)}%)"
        )
        lines.append(
            f"  Scheduled: {total} shifts  "
            f"(target ~{target})  |  "
            f"Day={day_c}  Eve={eve_c}  Night={ngt_c}"
        )

        # Weekly grid
        lines.append("  Week breakdown:")
        for w in range(schedule.num_weeks):
            week_start = schedule.start_date + timedelta(weeks=w)
            week_assignments = [
                a for a in assignments
                if week_start <= a.date < week_start + timedelta(weeks=1)
            ]
            cells = []
            for d in range(7):
                day = week_start + timedelta(days=d)
                day_shifts = [a for a in week_assignments if a.date == day]
                cells.append(SHIFT_SYMBOLS.get(day_shifts[0].shift_type, "?")
                              if day_shifts else ".")
            lines.append(
                f"    W{w+1:02d} [{week_start.strftime('%d %b')}]: "
                + " ".join(cells)
                + f"  ({len(week_assignments)} shifts)"
            )

    # Daily staffing levels
    lines.append("\n\nDAILY STAFFING LEVELS (nurses / doctors per shift)")
    lines.append("-" * 70)
    lines.append(f"{'Date':<14} {'Day-D':<7} {'Day-E':<7} {'Day-N':<7} "
                 f"{'Doc-D':<7} {'Doc-E':<7} {'Doc-N':<7}")

    nurses = [s for s in inputs.staff if s.role == Role.NURSE]
    doctors = [s for s in inputs.staff if s.role == Role.DOCTOR]

    for d in range(schedule.num_weeks * 7):
        curr_date = schedule.start_date + timedelta(days=d)
        day_assignments = schedule.get_day_assignments(curr_date)

        def count(role_staff, shift):
            names = {s.name for s in role_staff}
            return sum(1 for a in day_assignments
                       if a.staff_name in names and a.shift_type == shift)

        nd = count(nurses, ShiftType.DAY)
        ne = count(nurses, ShiftType.EVENING)
        nn = count(nurses, ShiftType.NIGHT)
        dd = count(doctors, ShiftType.DAY)
        de = count(doctors, ShiftType.EVENING)
        dn = count(doctors, ShiftType.NIGHT)

        flag = ""
        req = inputs.dept_requirements
        is_weekend = curr_date.weekday() >= 5 or curr_date in set(req.public_holidays)
        min_nd = req.min_nurses_weekend_day if is_weekend else req.min_nurses_day
        min_ne = req.min_nurses_weekend_evening if is_weekend else req.min_nurses_evening
        min_nn = req.min_nurses_weekend_night if is_weekend else req.min_nurses_night
        min_dd = req.min_doctors_weekend_day if is_weekend else req.min_doctors_day
        if nd < min_nd or ne < min_ne or nn < min_nn or dd < min_dd:
            flag = " ⚠ BELOW MIN"

        lines.append(
            f"{curr_date.strftime('%a %Y-%m-%d'):<14} "
            f"{nd:<7} {ne:<7} {nn:<7} {dd:<7} {de:<7} {dn:<7}{flag}"
        )

    # Broken preferences
    lines.append("\n\nBROKEN PREFERENCES")
    lines.append("-" * 70)
    if schedule.infeasible_preferences:
        for msg in schedule.infeasible_preferences:
            lines.append(f"  • {msg}")
    else:
        lines.append("  None — all soft preferences were honoured.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_REPORT_SYSTEM = """\
You are an expert healthcare scheduling analyst and communicator.
You will receive a raw schedule summary for a hospital ward and must produce
a clear, professional narrative report in Swedish-style plain English suitable
for the ward manager (avdelningschef).

Structure your report as follows:

1. EXECUTIVE SUMMARY (2-3 sentences: period, solver outcome, headline finding)
2. COMPLIANCE CONFIRMATION (confirm all Swedish law constraints are met, or flag any issues)
3. STAFFING COVERAGE ANALYSIS (highlight days/shifts that are thin, well-covered, or at risk)
4. PREFERENCE TRADE-OFFS (explain which staff preferences could not be met and why,
   be empathetic and clear — these are people's working conditions)
5. RECOMMENDATIONS (1-3 actionable suggestions for the ward manager)

Tone: professional, clear, compassionate. Avoid jargon. Keep it under 600 words.
"""


def _call_llm(summary_text: str, schedule: Schedule, inputs: ParsedInputs) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    user_message = (
        f"Please produce the schedule report for the following schedule summary.\n\n"
        f"{summary_text}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=_REPORT_SYSTEM,
        messages=[{"role": "user", "content": user_message}],
    )

    llm_report = response.content[0].text.strip()

    # Append the raw summary as an appendix
    return (
        llm_report
        + "\n\n"
        + "=" * 70
        + "\nAPPENDIX — RAW SCHEDULE DATA\n"
        + "=" * 70
        + "\n"
        + summary_text
    )
