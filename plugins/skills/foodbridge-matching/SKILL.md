# FoodBridge Matching Skill

Auto-activating skill for FoodBridge matching operations.

## Activation Triggers

Activates when user mentions:
- "food match" or "match food"
- "allocate surplus" or "distribute meals"
- "FoodBridge"
- "shelter allocation"
- "meal distribution"

## Capabilities

| Capability | Description |
|------------|-------------|
| `execute_match` | Run match with custom parameters |
| `explain_scoring` | Break down scoring components |
| `analyze_allocation` | Analyze why shelters got specific amounts |
| `recommend_params` | Suggest radius/weight adjustments |

## Usage Examples

**User:** "Match the surplus food to shelters"
→ Skill activates, asks for surplus_id and radius, executes match

**User:** "Why did Shelter B only get 30 meals?"
→ Skill activates, explains two-pass allocation and scoring

**User:** "How can I get more meals allocated?"
→ Skill activates, recommends: increase radius, adjust weights, check dietary tags

## Implementation

Tools used:
- `foodbridge_match` - Execute match
- `foodbridge_list_surplus` - Check available lots
- `foodbridge_list_shelters` - Check shelter availability

## Auto-Activation Keywords

- "match"
- "allocate"
- "surplus"
- "shelter"
- "foodbridge"
- "distribute"