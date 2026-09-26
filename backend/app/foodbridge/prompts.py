"""FoodBridge prompts - coordinator natural-language summary only.

The deterministic summary template lives here so demo mode never pretends an
LLM wrote it: LLM output is tagged with its provider, fallbacks are tagged
[FALLBACK].
"""

COORDINATOR_SYSTEM = """You are the FoodBridge coordinator, an assistant for restaurant staff.
You receive the JSON output of a food-surplus matching workflow.
Write a short, friendly summary (3-5 sentences): how many meals go to which shelter,
distance, why those shelters were picked, and what to do next (pickup timing).
Never invent numbers not present in the data. If mock/demo mode is indicated, start with [DEMO MODE].
"""

SUMMARY_PROMPT_TEMPLATE = """Summarize this FoodBridge match result for the restaurant.

Restaurant: {restaurant}
Surplus: {meals} meals ({food_types}), expires in {hours_remaining:.1f}h
Allocations:
{allocation_lines}
Unallocated: {unallocated} meals
Verification: {verification_note}
Retries used: {retry_count}

Give a 3-5 sentence summary with pickup guidance."""

FALLBACK_SUMMARY_TEMPLATE = """[FALLBACK] {restaurant} surplus of {meals} meals matched: {allocation_line} {unallocated} meals unallocated. Verification {verification_note}."""


def build_summary_prompt(state: dict) -> str:
    restaurant = (state.get("restaurant") or {}).get("name", "unknown restaurant")
    surplus = state.get("surplus") or {}
    allocs = state.get("allocations") or []
    lines = []
    for a in allocs:
        lines.append(
            f"- {a.get('shelter_name', a.get('shelter_id'))}: {a.get('meals')} meals, "
            f"{a.get('distance_km')} km (score {a.get('score')})"
        )
    verification = state.get("verification") or {}
    note = "passed" if verification.get("passed") else "failed"
    return SUMMARY_PROMPT_TEMPLATE.format(
        restaurant=restaurant,
        meals=surplus.get("meal_count", 0),
        food_types=", ".join(surplus.get("food_types") or []) or "unspecified",
        hours_remaining=float(state.get("hours_remaining") or 0.0),
        allocation_lines="\n".join(lines) if lines else "- none (no eligible shelter)",
        unallocated=state.get("unallocated", 0),
        verification_note=note,
        retry_count=state.get("retry_count", 0),
    )


def build_fallback_summary(state: dict) -> str:
    restaurant = (state.get("restaurant") or {}).get("name", "unknown restaurant")
    surplus = state.get("surplus") or {}
    allocs = state.get("allocations") or []
    parts = [f"{a.get('shelter_name', a.get('shelter_id'))}: {a.get('meals')} meals" for a in allocs]
    verification = state.get("verification") or {}
    return FALLBACK_SUMMARY_TEMPLATE.format(
        restaurant=restaurant,
        meals=surplus.get("meal_count", 0),
        allocation_line=("; ".join(parts) + ".") if parts else "no eligible shelter.",
        unallocated=state.get("unallocated", 0),
        verification_note="passed" if verification.get("passed") else "failed",
    )


DEMO_SUMMARY_TEMPLATE = """[DEMO MODE] {restaurant} has {meals} surplus meals to distribute. Plan: {allocation_line} {unallocated} meal(s) remain unallocated. Verification passed on attempt {attempt}."""

DEMO_ERROR_SUMMARY_TEMPLATE = """[DEMO MODE] Match failed with code {code}: {message} ({issue_count} issue(s) reported by verification)."""


def deterministic_summary(state: dict) -> str:
    """Labeled demo-mode template - used when DEMO_MODE is active (no real LLM)."""
    restaurant = (state.get("restaurant") or {}).get("name", "unknown restaurant")
    surplus = state.get("surplus") or {}
    allocs = state.get("allocations") or []
    parts = [f"{a.get('shelter_name', a.get('shelter_id'))}: {a.get('meals')} meals" for a in allocs]
    return DEMO_SUMMARY_TEMPLATE.format(
        restaurant=restaurant,
        meals=surplus.get("meal_count", 0),
        allocation_line=("; ".join(parts) + ".") if parts else "no eligible shelter.",
        unallocated=state.get("unallocated", 0),
        attempt=1 + int(state.get("retry_count", 0)),
    )


def deterministic_error_summary(error: dict, state: dict) -> str:
    return DEMO_ERROR_SUMMARY_TEMPLATE.format(
        code=error.get("code", "UNKNOWN"),
        message=error.get("message", ""),
        issue_count=len(error.get("details") or []),
    )
