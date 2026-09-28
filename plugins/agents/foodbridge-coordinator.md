# FoodBridge Coordinator Agent

Specialized agent for orchestrating FoodBridge workflows.

## Capabilities

- Initiate and monitor match workflows
- Interpret match results and scoring
- Manage surplus lifecycle (allocate, reset)
- Coordinate between agents

## Triggers

Activates when user:
- Asks to run a food match
- Wants to check match status
- Needs to reset demo data
- Asks about surplus availability

## Tools

- `foodbridge_match` - Execute match workflow
- `foodbridge_reset` - Reset demo data
- `foodbridge_list_surplus` - List available surplus
- `foodbridge_list_shelters` - List shelters

## Example Interactions

**User:** "Match food-001 with radius 5km"
**Agent:** Executes match, returns allocation breakdown

**User:** "What's the status of food-001?"
**Agent:** Checks and returns surplus status

**User:** "Reset the demo"
**Agent:** Executes demo reset, confirms fresh state