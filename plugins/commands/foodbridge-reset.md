# /foodbridge:reset Command

Reset FoodBridge demo data.

## Syntax

```
/foodbridge:reset [--confirm]
```

## Options

| Option | Description |
|--------|-------------|
| `--confirm` | Skip confirmation prompt |

## Examples

```
/foodbridge:reset
/foodbridge:reset --confirm
```

## Response Format

```
✅ Demo data reset successfully
- Restaurant: Green Leaf Restaurant
- Shelters: Shelter A, Shelter B, Shelter C
- Surplus: food-001 (80 meals, available)
- Event bus: Cleared
```

## Use Cases

- Reset between demo runs
- Clear in-flight match claims
- Fresh start for testing

## Implementation

Calls: `POST /api/foodbridge/demo/reset`