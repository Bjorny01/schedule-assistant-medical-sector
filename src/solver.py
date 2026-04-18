"""
Constraint solver for the Medical Staff Rostering System.

Uses Google OR-Tools CP-SAT to find a schedule that:
  1. Satisfies all Tier 1 (law) hard constraints
  2. Satisfies all Tier 2 (operational) hard constraints
  3. Satisfies all Tier 3 personal hard needs
  4. Maximises soft preferences via a weighted objective

Law constraints implemented (see swedish_work_law.txt for references):
  HC-01  At most 1 shift per person per calendar day
  HC-02  Evening(d) → Day(d+1) forbidden          [11 h rest]
  HC-03  Night(d)   → Day(d+1) forbidden          [11 h rest]
  HC-04  Night(d)   → Evening(d+1) forbidden      [11 h rest]
  HC-05  At most 5 shifts per 7-day week           [40 h/week]
  HC-06  At most 5 working days in any 6-day window [no 6 consecutive days]
  HC-07  At most 8 night shifts per 4-week block
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from ortools.sat.python import cp_model

from .models import (
    DepartmentRequirements,
    ParsedInputs,
    Role,
    Schedule,
    ShiftAssignment,
    ShiftType,
    Staff,
    WorkLawRules,
)

# Convenience constants (shift indices)
DAY_IDX = 0
EVE_IDX = 1
NGT_IDX = 2
NUM_SHIFTS = 3
SHIFT_TYPES = [ShiftType.DAY, ShiftType.EVENING, ShiftType.NIGHT]

# Objective weights
W_AVOID_SHIFT = 10       # penalty: scheduled on an avoided shift type
W_PREF_DAY_OFF = 4       # penalty: scheduled on a preferred-off weekday
W_FILL_CONTRACT = 6      # bonus:   each shift scheduled (drives contract fill)
W_PREFERRED_SHIFT = 4    # bonus:   scheduled on a preferred shift type
W_EXCESS_NIGHTS = 15     # penalty: each night above weekly soft limit
W_SCATTERED_DAYS_OFF = 3 # penalty: isolated day off (when consecutive preferred)


def build_schedule(
    inputs: ParsedInputs,
    start_date: date,
    num_weeks: int = 8,
    solver_time_limit_s: int = 120,
) -> Optional[Schedule]:
    """
    Build a schedule for the given inputs and planning horizon.

    Returns a Schedule on success, or None if the problem is infeasible.
    """
    model = cp_model.CpModel()
    staff_list = inputs.staff
    dept_req = inputs.dept_requirements
    law = inputs.law_rules
    num_days = num_weeks * 7

    # ------------------------------------------------------------------
    # Decision variables
    # shifts[(si, d, s)] = 1 if staff[si] works shift s on day d
    # ------------------------------------------------------------------
    shifts: dict[tuple[int, int, int], cp_model.IntVar] = {}
    for si in range(len(staff_list)):
        for d in range(num_days):
            for s in range(NUM_SHIFTS):
                shifts[(si, d, s)] = model.NewBoolVar(
                    f"sh_{staff_list[si].name}_{d}_{s}"
                )

    # ------------------------------------------------------------------
    # TIER 1 — LAW HARD CONSTRAINTS
    # ------------------------------------------------------------------

    for si in range(len(staff_list)):
        # HC-01: at most 1 shift per person per day
        for d in range(num_days):
            model.AddAtMostOne([shifts[(si, d, s)] for s in range(NUM_SHIFTS)])

        # HC-02/03/04: 11-hour rest between shifts
        for d in range(num_days - 1):
            # Evening(d) → Day(d+1): only 8 h gap
            model.Add(shifts[(si, d, EVE_IDX)] + shifts[(si, d + 1, DAY_IDX)] <= 1)
            # Night(d) → Day(d+1): 0 h gap
            model.Add(shifts[(si, d, NGT_IDX)] + shifts[(si, d + 1, DAY_IDX)] <= 1)
            # Night(d) → Evening(d+1): only 8 h gap
            model.Add(shifts[(si, d, NGT_IDX)] + shifts[(si, d + 1, EVE_IDX)] <= 1)

        # HC-05: at most 5 shifts per 7-day week (40 h/week)
        for w in range(num_weeks):
            week_shifts = [
                shifts[(si, w * 7 + d, s)]
                for d in range(7)
                for s in range(NUM_SHIFTS)
            ]
            model.Add(sum(week_shifts) <= law.max_shifts_per_week)

        # HC-06: no more than 5 working days in any rolling 6-day window
        for d in range(num_days - 5):
            window = [
                shifts[(si, d + dd, s)]
                for dd in range(6)
                for s in range(NUM_SHIFTS)
            ]
            model.Add(sum(window) <= law.max_consecutive_work_days)

        # HC-07: at most 8 night shifts per 4-week block
        for block in range(0, num_days, 28):
            block_end = min(block + 28, num_days)
            night_shifts = [
                shifts[(si, d, NGT_IDX)]
                for d in range(block, block_end)
            ]
            model.Add(sum(night_shifts) <= law.max_night_shifts_per_4weeks)

    # ------------------------------------------------------------------
    # TIER 2 — OPERATIONAL HARD CONSTRAINTS
    # ------------------------------------------------------------------

    nurses = [si for si, s in enumerate(staff_list) if s.role == Role.NURSE]
    doctors = [si for si, s in enumerate(staff_list) if s.role == Role.DOCTOR]
    holiday_set = set(dept_req.public_holidays)

    for d in range(num_days):
        curr_date = start_date + timedelta(days=d)
        is_weekend = curr_date.weekday() >= 5 or curr_date in holiday_set

        for shift_idx in range(NUM_SHIFTS):
            nurse_sum = sum(shifts[(si, d, shift_idx)] for si in nurses)
            doc_sum = sum(shifts[(si, d, shift_idx)] for si in doctors)

            if shift_idx == DAY_IDX:
                n_min = dept_req.min_nurses_weekend_day if is_weekend else dept_req.min_nurses_day
                d_min = dept_req.min_doctors_weekend_day if is_weekend else dept_req.min_doctors_day
            elif shift_idx == EVE_IDX:
                n_min = dept_req.min_nurses_weekend_evening if is_weekend else dept_req.min_nurses_evening
                d_min = dept_req.min_doctors_weekend_evening if is_weekend else dept_req.min_doctors_evening
            else:  # NIGHT
                n_min = dept_req.min_nurses_weekend_night if is_weekend else dept_req.min_nurses_night
                d_min = dept_req.min_doctors_weekend_night if is_weekend else dept_req.min_doctors_night

            model.Add(nurse_sum >= n_min)
            model.Add(doc_sum >= d_min)

    # ------------------------------------------------------------------
    # TIER 3 — PERSONAL HARD CONSTRAINTS
    # ------------------------------------------------------------------

    for si, staff in enumerate(staff_list):
        c = staff.constraints

        # Mandatory specific dates off (whole day)
        for off_date in c.mandatory_days_off:
            d_idx = (off_date - start_date).days
            if 0 <= d_idx < num_days:
                for s in range(NUM_SHIFTS):
                    model.Add(shifts[(si, d_idx, s)] == 0)

        # Mandatory specific shifts off (single shift on a specific date)
        for off_date, shift_type in c.mandatory_shifts_off:
            d_idx = (off_date - start_date).days
            if 0 <= d_idx < num_days:
                s_idx = SHIFT_TYPES.index(shift_type)
                model.Add(shifts[(si, d_idx, s_idx)] == 0)

        # Recurring weekday off (whole day)
        for weekday in c.recurring_days_off:
            for d in range(num_days):
                if (start_date + timedelta(days=d)).weekday() == weekday:
                    for s in range(NUM_SHIFTS):
                        model.Add(shifts[(si, d, s)] == 0)

        # Recurring shift off (specific shift on a specific weekday)
        for weekday, shift_type in c.recurring_shifts_off:
            s_idx = SHIFT_TYPES.index(shift_type)
            for d in range(num_days):
                if (start_date + timedelta(days=d)).weekday() == weekday:
                    model.Add(shifts[(si, d, s_idx)] == 0)

        # Allowed shift types (hard medical / contractual restriction)
        if c.allowed_shifts is not None:
            allowed_idxs = {SHIFT_TYPES.index(st) for st in c.allowed_shifts}
            for d in range(num_days):
                for s in range(NUM_SHIFTS):
                    if s not in allowed_idxs:
                        model.Add(shifts[(si, d, s)] == 0)

        # Weekly shift cap from contract
        for w in range(num_weeks):
            week_shifts = [
                shifts[(si, w * 7 + d, s)]
                for d in range(7)
                for s in range(NUM_SHIFTS)
            ]
            model.Add(sum(week_shifts) <= c.max_weekly_shifts)

    # ------------------------------------------------------------------
    # SOFT CONSTRAINTS — weighted objective terms
    # ------------------------------------------------------------------

    obj_terms: list[cp_model.LinearExprT] = []

    for si, staff in enumerate(staff_list):
        prefs = staff.constraints.preferences

        for d in range(num_days):
            curr_date = start_date + timedelta(days=d)
            dow = curr_date.weekday()  # 0=Monday

            for s, shift_type in enumerate(SHIFT_TYPES):
                var = shifts[(si, d, s)]

                # Penalty: scheduling on an avoided shift type
                if shift_type in prefs.avoid_shifts:
                    obj_terms.append(W_AVOID_SHIFT * var)

                # Bonus: scheduling on a preferred shift type
                if shift_type in prefs.preferred_shifts:
                    obj_terms.append(-W_PREFERRED_SHIFT * var)

                # Penalty: scheduling on a preferred-off weekday
                if dow in prefs.preferred_days_off:
                    obj_terms.append(W_PREF_DAY_OFF * var)

                # Penalty: scheduling on a preferred-off (weekday, shift) pair
                if (dow, shift_type) in prefs.preferred_shifts_off:
                    obj_terms.append(W_PREF_DAY_OFF * var)

                # Bonus: filling contract hours (drives scheduler to use available slots)
                obj_terms.append(-W_FILL_CONTRACT * var)

        # Penalty: excess night shifts per week beyond soft limit
        for w in range(num_weeks):
            night_count_expr = sum(
                shifts[(si, w * 7 + d, NGT_IDX)] for d in range(7)
            )
            excess = model.NewIntVar(0, 7, f"excess_nights_{si}_{w}")
            model.Add(excess >= night_count_expr - prefs.max_night_shifts_per_week)
            model.Add(excess >= 0)
            obj_terms.append(W_EXCESS_NIGHTS * excess)

        # Soft penalty: prefer consecutive days off (cluster rest days)
        if prefs.prefer_consecutive_days_off:
            # Penalise isolated single days off (off on day d but working d-1 and d+1)
            for d in range(1, num_days - 1):
                working_prev = model.NewBoolVar(f"wprev_{si}_{d}")
                working_curr = model.NewBoolVar(f"wcurr_{si}_{d}")
                working_next = model.NewBoolVar(f"wnext_{si}_{d}")

                model.Add(working_prev == sum(shifts[(si, d - 1, s)] for s in range(NUM_SHIFTS)))
                model.Add(working_curr == sum(shifts[(si, d, s)] for s in range(NUM_SHIFTS)))
                model.Add(working_next == sum(shifts[(si, d + 1, s)] for s in range(NUM_SHIFTS)))

                # isolated_off = prev_working AND curr_off AND next_working
                isolated_off = model.NewBoolVar(f"isolated_off_{si}_{d}")
                curr_off = model.NewBoolVar(f"curr_off_{si}_{d}")
                model.Add(curr_off == 1 - working_curr)
                model.AddBoolAnd([working_prev, curr_off, working_next]).OnlyEnforceIf(isolated_off)
                model.AddBoolOr(
                    [working_prev.Not(), working_curr, working_next.Not()]
                ).OnlyEnforceIf(isolated_off.Not())
                obj_terms.append(W_SCATTERED_DAYS_OFF * isolated_off)

    # Minimise total weighted penalty (bonuses are negative penalties)
    model.Minimize(sum(obj_terms))

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = solver_time_limit_s
    solver.parameters.log_search_progress = True
    solver.parameters.num_search_workers = 4

    status = solver.Solve(model)

    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"[solver] No feasible solution found. Status: {status_name}")
        return None

    print(f"[solver] Solution found. Status: {status_name}  "
          f"Objective: {solver.ObjectiveValue():.1f}")

    # ------------------------------------------------------------------
    # Extract solution
    # ------------------------------------------------------------------

    assignments: list[ShiftAssignment] = []
    broken_prefs: list[str] = []

    for si, staff in enumerate(staff_list):
        prefs = staff.constraints.preferences
        for d in range(num_days):
            curr_date = start_date + timedelta(days=d)
            for s, shift_type in enumerate(SHIFT_TYPES):
                if solver.Value(shifts[(si, d, s)]) == 1:
                    assignments.append(
                        ShiftAssignment(
                            staff_name=staff.name,
                            date=curr_date,
                            shift_type=shift_type,
                        )
                    )
                    if shift_type in prefs.avoid_shifts:
                        broken_prefs.append(
                            f"{staff.name}: scheduled {shift_type.value} on "
                            f"{curr_date} (preference: avoid this shift type)"
                        )
                    dow = curr_date.weekday()
                    if dow in prefs.preferred_days_off:
                        broken_prefs.append(
                            f"{staff.name}: scheduled on {curr_date.strftime('%A')} "
                            f"{curr_date} (preference: day off)"
                        )
                    if (dow, shift_type) in prefs.preferred_shifts_off:
                        broken_prefs.append(
                            f"{staff.name}: scheduled {shift_type.value} on "
                            f"{curr_date.strftime('%A')} {curr_date} "
                            f"(preference: {shift_type.value} off on that weekday)"
                        )

    return Schedule(
        assignments=assignments,
        start_date=start_date,
        num_weeks=num_weeks,
        infeasible_preferences=broken_prefs,
        solver_status=status_name,
        objective_value=solver.ObjectiveValue(),
    )
