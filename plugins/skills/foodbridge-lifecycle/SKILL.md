# FoodBridge Lifecycle Skill

Auto-activating skill for FoodBridge surplus lifecycle management.

## Activation Triggers

Activates when user mentions:
- "surplus status" or "lot status"
- "consumed" or "allocated"
- "demo reset" or "reset demo"
- "409" or "already allocated"
- "in progress" or "claimed"

## Capabilities

| Capability | Description |
|------------|-------------|
| `check_status` | Check surplus lot status |
| `execute_reset` | Reset demo data |
| `explain_lifecycle` | Explain available → allocated states |
| `check_claims` | Check in-flight match claims |

## Usage Examples

**User:** "Is food-001 still available?"
→ Skill activates, checks and returns status

**User:** "I got a 409 error"
→ Skill activates, explains: lot consumed or in-flight

**User:** "Reset the demo for next presentation"
→ Skill activates, executes demo reset

**User:** "How does the lifecycle work?"
→ Skill activates, explains: available → (match) → allocated

## Implementation

Tools used:
- `foodbridge_list_surplus` - Check lot status
- `foodbridge_reset` - Reset demo data
- `foodbridge_match` - Test availability

## Auto-Activation Keywords

- "status"
- "available"
- "allocated"
- "consumed"
- "reset"
- "409"
- "demo"