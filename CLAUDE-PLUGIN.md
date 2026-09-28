# CLAUDE-PLUGIN.md

> Plugin system for extending hackathon-starter with AI capabilities

## Overview

This project supports a plugin architecture for extending AI capabilities, inspired by the prompts.chat plugin system. The plugin system allows adding:

- **MCP Servers** - Model Context Protocol servers for tool access
- **Slash Commands** - Custom commands for AI assistants
- **Agents** - Specialized agents for complex workflows
- **Skills** - Auto-activating skill modules

## Plugin Structure

```
plugins/
├── mcp/                    # MCP Server definitions
│   └── foodbridge/         # FoodBridge MCP server
├── commands/               # Slash command definitions
│   ├── foodbridge-match.md
│   └── foodbridge-reset.md
├── agents/                 # Specialized agents
│   ├── foodbridge-coordinator.md
│   └── foodbridge-analyst.md
└── skills/                 # Auto-activating skills
    ├── foodbridge-matching/
    └── foodbridge-lifecycle/
```

## Available Commands

### FoodBridge Match

```
/foodbridge:match <surplus_id> [radius_km]
/foodbridge:match food-001 --radius 5
/foodbridge:match food-001 --shelter-a,shelter-b
```

### FoodBridge Reset

```
/foodbridge:reset
/foodbridge:reset --confirm
```

## MCP Tools

### FoodBridge MCP Server

Provides tools for FoodBridge operations:

| Tool | Description |
|------|-------------|
| `foodbridge_match` | Execute a match workflow |
| `foodbridge_reset` | Reset demo data |
| `foodbridge_list_surplus` | List available surplus lots |
| `foodbridge_list_shelters` | List shelters |
| `foodbridge_get_events` | Get agent events for workflow |

## Agents

### FoodBridge Coordinator

Helps with:
- Orchestrating multi-agent workflows
- Interpreting match results
- Managing surplus lifecycle

### FoodBridge Analyst

Helps with:
- Analyzing match results and scoring breakdowns
- Explaining allocation decisions
- Identifying optimization opportunities

## Skills (Auto-Activating)

### FoodBridge Matching Skill

Activates when:
- User asks about food matching
- User wants to allocate surplus food
- User mentions FoodBridge

Capabilities:
- Execute matches with custom parameters
- Explain scoring breakdowns
- Recommend optimal radius/shelter selection

### FoodBridge Lifecycle Skill

Activates when:
- User asks about surplus status
- User wants to reset demo
- User mentions consumed/allocated lots

Capabilities:
- Check surplus availability
- Execute demo reset
- Explain lifecycle states (available → allocated)

## Installation

### For Claude Code

```bash
# Add plugin marketplace (if available)
/plugin marketplace add hackathon-starter/foodbridge

# Install plugin
/plugin install foodbridge@hackathon-starter
```

### Manual Setup

1. Copy plugin files to your `.claude/plugins/` directory
2. Configure MCP servers in `.mcp.json`
3. Add slash commands to your command palette

## Configuration

### Environment Variables

```bash
# Optional: API key for authenticated operations
FOODBRIDGE_API_KEY=your_key_here

# Optional: Custom backend URL
FOODBRIDGE_BACKEND_URL=http://localhost:8000
```

### MCP Server Config (`.mcp.json`)

```json
{
  "mcpServers": {
    "foodbridge": {
      "command": "python",
      "args": ["-m", "mcp.server", "foodbridge"],
      "env": {
        "FOODBRIDGE_API_KEY": "${FOODBRIDGE_API_KEY}"
      }
    }
  }
}
```

## Development

### Adding a New Command

1. Create `plugins/commands/your-command.md`
2. Define command syntax and examples
2. Register in command registry

### Adding a New Agent

1. Create `plugins/agents/your-agent.md`
2. Define agent capabilities and triggers
3. Register in agent registry

### Adding a New Skill

1. Create `plugins/skills/your-skill/SKILL.md`
2. Define auto-activation triggers
3. Define skill capabilities

### Adding an MCP Tool

1. Implement tool in `plugins/mcp/your-server/`
2. Define tool schema (JSON Schema)
3. Register in MCP server manifest

## Links

- [FoodBridge Architecture](docs/foodbridge.md)
- [API Contract](docs/api-contract.md)
- [MCP Specification](https://modelcontextprotocol.io/)