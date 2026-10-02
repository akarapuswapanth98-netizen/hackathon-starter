# Vibe3D - Frontend Generation & Visualization Module

**Hackathon Toolkit V2** - Optional frontend generation and visualization module.

Vibe3D generates React/Vue/Svelte/Next/Astro/Vanilla frontends from OpenAPI schemas
and provides 3D visualization capabilities for the Hackathon Starter backend.

## Status: Optional Module

Vibe3D is **optional** and does not affect backend execution.

```bash
# Install Vibe3D dependencies
cd hackathon-starter
npm install  # or: pip install -r requirements-3d.txt (if applicable)
```

## Quick Start

### Generate a frontend from OpenAPI

```bash
# Generate React frontend from local OpenAPI file
npx vibe3d generate foodbridge --api ./openapi.json --framework react

# Generate with 3D visualization
npx vibe3d generate foodbridge --api http://localhost:8000/openapi.json --framework react --3d

# Generate without 3D
npx vibe3d generate foodbridge --api http://localhost:8000/openapi.json --framework react --no-3d
```

### FoodBridge-specific generation

```bash
# Generate FoodBridge frontend with all required views
npx vibe3d generate foodbridge \
  --api http://localhost:8000/openapi.json \
  --framework react \
  --3d \
  --modes minimal,glass,cinematic

# Generate FoodBridge frontend without 3D
npx vibe3d generate foodbridge \
  --api http://localhost:8000/openapi.json \
  --framework react \
  --no-3d
```

## Architecture

Vibe3D sits **outside** the FoodBridge backend:

```
┌─────────────────────────────────────────┐
│             Hackathon Toolkit V2         │
│  ┌─────────────────────┐  ┌────────────┐ │
│  │  FoodBridge Backend │  │  Vibe3D    │ │
│  │  (FastAPI + LangGraph) │  │  (Optional) │ │
│  └─────────────────────┘  └────────────┘ │
│             │                       │       │
│             ▼                       ▼       │
│    /api/foodbridge/*             Generation│
│             │                       Types│
│             ▼                       Client │
│    API responses                  UI Components│
└─────────────────────────────────────────┘
```

Vibe3D **never** modifies the FoodBridge backend. It only consumes the public API.

## Modules

```
modules/vibe3d/
├── cli/              # Command-line interface
├── generator/        # Frontend code generator
├── scraper/        # OpenAPI/schema scraper
├── analyzer/       # Schema analyzer & type generator
├── templates/      # React/Vue/Svelte/Next templates
├── preview/        # Development preview server
├── openapi/        # OpenAPI parsing & validation
├── integrations/   # Backend integrations
│   └── foodbridge/ # FoodBridge-specific generation
├── tests/          # Vibe3D test suite
└── README.md
```

## Design Modes

Supported visual modes:

- `minimal` - Clean, simple interface
- `glass` - Glassmorphism styling
- `cinematic` - Cinematic lighting and effects
- `dark-tech` - Dark theme with tech aesthetic
- `3d-spatial` - 3D spatial visualization (when 3D enabled)
- `dashboard` - Dashboard-focused layout
- `education` - Education-focused layout
- `environmental` - Environmental/thematic layout
- `medical` - Medical/themed layout
- `fintech` - Fintech/themed layout

## Modes: LIVE / DEMO / AUTO

The generated frontend respects the backend mode:

- `LIVE` - Connects to real backend API
- `DEMO` - Uses demo/reset endpoints where supported
- `AUTO` - Live backend when available; demo fallback otherwise

Mode is displayed in the UI.

## 3D Visualization (Optional)

When 3D is enabled:

- Three.js is lazy-loaded
- WebGL is detected; falls back to 2D if unavailable
- Reduced-motion preferences respected
- Visualizes: restaurant nodes, shelter nodes, allocation connections, agent workflow status, animated paths

When 3D is disabled:

- Normal 2D UI is shown
- No performance impact from Three.js

## Generated Frontend Structure

```
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts       # Auto-generated API client
│   │   └── generated.ts    # Generated types/interfaces
│   ├── types/
│   │   └── api-types.ts  # TypeScript types from OpenAPI
│   ├── components/
│   │   ├── Dashboard.jsx
│   │   ├── Restaurants.jsx
│   │   ├── Shelters.jsx
│   │   ├── Matching.jsx
│   │   ├── AllocationResults.jsx
│   │   ├── AgentEvents.jsx
│   │   └── MapVisualization.jsx
│   ├── pages/
│   │   ├── Home.jsx
│   │   ├── Dashboard.jsx
│   │   ├── Restaurants.jsx
│   │   ├── Matching.jsx
│   │   └── DemoControls.jsx
│   ├── hooks/
│   │   ├── useApiClient.jsx
│   │   └── useMode.jsx
│   └── App.jsx           # Composed from generated modules
├── public/
│   └── index.html
└── package.json
```

## Generated API Client

The generator creates a TypeScript API client from the OpenAPI schema:

```typescript
// Generated in src/api/generated.ts
import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000/api',
});

export interface FoodBridgeResponse {
  success: boolean;
  workflow_id: string;
  workflow_status: MatchStatus;
  allocation: Allocation[];
  total_allocated: number;
  unallocated: number;
  summary: string;
  summary_source: string;
  retry_count: number;
  metadata: {
    weights: number[];
    demo_mode: boolean;
    llm_provider: string;
    requested_radius_km: number;
    max_retries: number;
    duration_ms: number;
    logistics: any;
    surplus_status: string;
    surplus_remaining: number;
    error?: string;
  };
  agent_events: AgentEvent[];
}

export interface AgentEvent {
  agent: string;
  status: string;
  detail: string;
}

export interface MatchStatus {
  completed: string;
  failed: string;
  timeout: string;
}

// Export all types generated from OpenAPI
export type { /* ... all OpenAPI types ... */ };
```

## OpenAPI Generation

Vibe3D can generate the OpenAPI schema from the FastAPI backend:

```bash
# Generate OpenAPI JSON from running server
npx vibe3d generate openapi --url http://localhost:8000/openapi.json

# Or use the existing OpenAPI endpoint
npx vibe3d generate foodbridge --api http://localhost:8000/openapi.json
```

## FoodBridge Template Views

The FoodBridge template generates these required views:

1. **Dashboard** - Overview of matching status, total/allocated/unallocated meals
2. **Restaurants/Surplus** - List available surplus lots, create new lots
3. **Shelters** - List shelters with capacity, occupancy, urgency, dietary compatibility
4. **Matching** - Configure match parameters (radius, weights, shelters)
5. **Allocation Results** - Display allocation results from a match workflow
6. **Agent Workflow/Events** - Visualize the 6-agent workflow progression
7. **Map/Distance Visualization** - Haversine distances, route visualization
8. **Demo/Reset Controls** - Demo mode reset, LIVE/DEMO/AUTO mode display

## Visualization Components

### 2D Default (always available)

- Tables and lists for all data
- Forms for creating/managing surplus and shelters
- Match configuration forms
- Results display with structured data

### 3D (optional, lazy-loaded)

- Three.js scene with restaurant and shelter nodes
- Connection lines representing allocations
- Agent workflow status indicators
- Animated matching/delivery paths
- Distance/ETA labels

3D is **visual only** - never used for business logic decisions.

## Configuration

```javascript
// vite.config.ts or webpack config
import { vibe3dConfig } from '@hackathon/vibe3d/vite';

export default defineConfig({
  ...config,
  plugins: [vibe3dConfig({ 
    framework: 'react',
    threejs: true,
    modes: ['minimal', 'glass', 'cinematic'] 
  })],
});
```

## Requirements

### Frontend (optional install)

```bash
npm install three @types/three
npm install @tanstack/react-query
npm install @hookform/resolvers
npm install zod  # or yup for validation
npm install clsx  # class name joining
```

### Design mode dependencies (optional)

```bash
npm install @mui/material @emotion/react @emotion/styled
# or for Tailwind:
npm install daisyui
```

## License

MIT-licensed. See LICENSE for details.

## Support

This module is optional and maintained as part of the Hackathon Toolkit V2.
Issues and PRs welcome at the repository.

## Compatibility

- Python 3.11+
- Node.js 18+
- React 18.3+
- Vite 5.4+
- FastAPI 0.141+
- FoodBridge multi-agent system (preserved, unmodified)