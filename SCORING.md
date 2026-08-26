# BWIH Driver Scoring Rules

## Overview

Every Check-in record receives a score out of **100**. The score reflects whether the driver fulfilled the dispatch requirements for that trip: arriving on time at BWI, running the correct route, delivering to the destination on schedule, and bringing back return cargo when required.

A driver's overall rating is the **average of all task scores in the past 30 days**.

---

## Single-Task Scoring

```
Task Score = 100 − Route Error − Late Arrival − Destination Delay − Return Cargo − Manual Deduction
```

Minimum score is **0**. Deductions are independent and stack.

---

### 1. Route Error — Wrong Destination (instant 0)

| Situation | Score |
|-----------|-------|
| Correct route | No deduction |
| Wrong route / wrong destination | **Task score = 0** (overrides everything) |

A route error is the most severe issue. If a driver goes to the wrong location, the entire task is scored **0** regardless of other factors. The dispatcher marks "route correct = No" in the record detail page.

---

### 2. Late Arrival at BWI (−45)

The system compares **actual arrival time** (Check-in) against **scheduled arrival time**.

| Arrival | Deduction |
|---------|-----------|
| On time or early | 0 |
| Late (any amount) | **−45** |

> **Why binary?** In BWIH's dispatch flow, any delay at arrival affects the entire loading and departure chain. Whether a driver is 5 minutes or 50 minutes late, the dispatch plan has already been disrupted. The current rule treats all lateness equally.

The system handles overnight shifts automatically (e.g., scheduled 23:00, arrived 01:00 = 120 minutes late).

---

### 3. Destination Arrival Time

Drivers deliver to four stations. Each has an expected transit window from BWI:

| Destination | Address | Type | Estimated Drive Time |
|-------------|---------|------|---------------------|
| **IAD01** | 6714 Electronic Dr, Springfield, VA 22151 | Unload Only | ~1 hr |
| **DCA01** | 10726 Tucker St, Unit B, Beltsville, MD 20705 | Unload Only | ~45 min |
| **RIC01** | 1103 Oliver Hl Wy, Richmond, VA 23219 | Load and Unload | ~1.5 hr |
| **ORF01** | 30 Aberdeen Rd, Hampton, VA 23661 | Unload Only | ~3 hr |

> These are warehouse/facility locations, not airports. The codes (IAD, DCA, RIC, ORF) are internal route names only.

Whether a driver reaches the destination on time depends on two things:

1. **Did the driver depart BWI on time?** — Captured by the departure time from DMS Excel upload.
2. **Did the driver arrive at the destination within a reasonable window?** — Currently tracked by the DMS system; the dispatcher reviews and records any destination delay as part of the post-trip review.

**Scoring impact:**

| Situation | Treatment |
|-----------|-----------|
| Departed on time, arrived at destination on time | No deduction |
| Departed late due to late arrival at BWI | Already penalized under "Late Arrival" (−45) |
| Departed on time but arrived at destination late (driver issue, e.g., detour, extended stop) | Dispatcher applies **manual deduction** with reason |
| Arrived at destination late due to traffic / weather / facility closure | No deduction — not a driver fault. Recorded in notes for reference. |

> **Why not an automatic deduction?** Destination arrival timing depends on external factors (highway conditions, facility hours, weather). Automatic penalization would be unfair. The dispatcher reviews each case and applies a manual deduction only when the delay is attributable to the driver.

**Wait time at BWI** is also recorded:

```
Wait Time = Departure Time − Arrival Time
```

This is informational (helps evaluate warehouse efficiency) and does not affect the driver's score.

---

### 4. Return Cargo Not Completed (−10 to −25)

Certain routes (IAD, DCA, RIC) require the driver to bring back return cargo. This is marked at Check-in time.

| Return Cargo Result | Deduction |
|---------------------|-----------|
| Completed | 0 |
| Partially completed | **−10** |
| Not completed / not brought back | **−25** |
| Pending (not yet recorded) | 0 (recalculated when result is entered) |
| Not required for this trip | 0 |

> The dispatcher updates the return cargo result after the trip. The system recalculates the task score and driver average immediately.

---

### 5. Manual Deduction by Dispatcher (0 to −100)

The dispatcher can apply an additional deduction to any record. Each manual deduction requires:

| Field | Description |
|-------|-------------|
| Amount | 0–100 points |
| Category | `Behavior issue` / `Operational impact` / `Other` |
| Reason | Free text explanation |

Examples:
- Refused to cooperate at dock → Behavior issue, −15
- Blocked dock for 30+ minutes unnecessarily → Operational impact, −20
- Arrived at destination 2 hours late without explanation → Other, −30

All manual deductions are recorded with full audit trail.

---

## Scoring Examples

| Scenario | Calculation | Score |
|----------|-------------|-------|
| On time, correct route, cargo returned | 100 − 0 − 0 − 0 = 100 | **100** |
| Late to BWI, cargo returned | 100 − 45 − 0 = 55 | **55** |
| On time, cargo not returned | 100 − 0 − 25 = 75 | **75** |
| Late to BWI, cargo not returned | 100 − 45 − 25 = 30 | **30** |
| Late to BWI, cargo partially done | 100 − 45 − 10 = 45 | **45** |
| Wrong route (any combination) | Instant 0 | **0** |
| On time, dispatcher deducts 20 | 100 − 0 − 0 − 20 = 80 | **80** |
| Late, no cargo, dispatcher −10 | 100 − 45 − 25 − 10 = 20 | **20** |

---

## Driver Overall Score

```
Driver Score = Average of all task scores in the past 30 days
```

- New drivers with no records default to **100**.
- The score updates automatically whenever a Check-in record is saved, updated, or deleted.

---

## Rating Reference for Dispatch

| Grade | Score Range | Recommendation |
|-------|------------|----------------|
| **A** | ≥ 90 | Preferred for critical, time-sensitive, and return-cargo routes |
| **B** | 80–89 | Normal assignment |
| **C** | 70–79 | Can assign, but have a backup plan for critical routes |
| **D** | < 70 | Do not assign as primary driver without dispatcher approval |

---

## Red Flags (Require Dispatcher Attention)

Even if the overall score looks acceptable, the dispatcher should review a driver's history when:

- **1 route error** has occurred (went to wrong destination)
- **1 return cargo failure** (required but not brought back)
- **2+ late arrivals** in the past 30 days
- The actual driver does not match the scheduled driver

---

## Scoring Timeline

```
Step 1: Check-in
         ↓  System records arrival time vs. scheduled time
         ↓  Calculates late deduction automatically
         ↓  Return cargo result = "pending" (no deduction yet)
         ↓  Initial score generated

Step 2: DMS Excel Upload / Manual Entry
         ↓  Departure time and MT task code recorded
         ↓  Wait time calculated
         ↓  Dispatcher confirms route correctness

Step 3: Post-Trip Review
         ↓  Dispatcher records return cargo result
         ↓  Dispatcher records destination arrival issues (if any)
         ↓  Dispatcher applies manual deduction (if warranted)
         ↓  Score recalculated, driver average updated

Every save triggers an immediate recalculation.
```

---

## Data Stored Per Task

| Field | Description |
|-------|-------------|
| Scheduled arrival time | When the driver was expected at BWI |
| Actual arrival time | When the driver checked in |
| Late minutes | Auto-calculated (negative = early) |
| Destination | IAD / DCA / RIC / ORF |
| Departure time | From DMS data |
| Wait time (minutes) | Departure − Arrival (informational) |
| Route correct | Yes / No |
| Return cargo required | Yes / No |
| Return cargo result | Completed / Partial / Not completed / Pending |
| Manual deduction | 0–100 |
| Deduction category | Behavior / Operational / Other |
| Deduction reason | Free text |
| Task score | Auto-calculated |
| DMS task ID (MT code) | Links to the DMS system record |
