# /foodbridge:match Command

Execute a FoodBridge match workflow.

## Syntax

```
/foodbridge:match <surplus_id> [options]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--radius <km>` | Search radius in kilometers | 10 |
| `--shelters <ids>` | Comma-separated shelter IDs | All eligible |
| `--no-summary` | Skip natural-language summary | false |

## Examples

```
/foodbridge:match food-001
/foodbridge:match food-001 --radius 5
/foodbridge:match food-001 --shelters shelter-a,shelter-b
/foodbridge:match food-001 --radius 2.5 --no-summary
```

## Response Format

```
✅ Match completed: food-001
Total allocated: 80 meals
Shelters: Shelter A (50), Shelter B (30)
Summary: [DEMO MODE] Match completed for Green Leaf Restaurant...
Workflow ID: abc123
```

## Error Responses

```
❌ 409 - Surplus lot food-001 has already been allocated
❌ 404 - Surplus lot food-xxx not found
❌ 422 - Invalid radius (must be > 0 and ≤ 100)
```

## Implementation

Calls: `POST /api/foodbridge/match`