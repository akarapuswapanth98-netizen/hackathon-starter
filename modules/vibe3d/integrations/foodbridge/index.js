#!/usr/bin/env node
"""Vibe3D FoodBridge Integration.

Handles FoodBridge-specific generation and configuration for the Vibe3D module.

Provides:
- FoodBridge API endpoint discovery
- Mode-aware frontend generation
- 3D visualization configuration
- LIVE/DEMO/AUTO mode support
"""

import fs from 'fs'
import path from 'path'

const __dirname = path.dirname(__filename)
const VIBE3D_DIR = path.join(__dirname, '..')

/** FoodBridge API endpoint configuration */
export const FOODBRIDGE_API = {
  BASE: '/api/foodbridge',
  ENDPOINTS: {
    RESTAURANTS: '/restaurants',
    SHELTERS: '/shelters',
    SURPLUS: '/surplus',
    MATCH: '/match',
    EVENTS: '/agents/events',
    DEMO_RESET: '/demo/reset',
    // Full paths
    LIST_RESTAURANTS: '/api/foodbridge/restaurants',
    LIST_SHELTERS: '/api/foodbridge/shelters',
    LIST_SURPLUS: '/api/foodbridge/surplus',
    CREATE_SURPLUS: '/api/foodbridge/surplus',
    RUN_MATCH: '/api/foodbridge/match',
    LIST_EVENTS: '/api/foodbridge/agents/events',
    DEMO_RESET_ENDPOINT: '/api/foodbridge/demo/reset',
  },
  // LIVE / DEMO / AUTO mode behaviors
  MODES: {
    LIVE: {
      description: 'Use real backend API',
      demoReset: 'Allowed with authentication',
      match: 'Real match workflow',
    },
    DEMO: {
      description: 'Use backend demo functionality',
      demoReset: 'Full demo reset allowed',
      match: 'Uses demo data; real workflow simulated',
    },
    AUTO: {
      description: 'Live backend when available; otherwise demo fallback',
      demoReset: 'Falls back to demo mode if no live backend',
      match: 'Auto-detects and uses available mode',
    },
  },
}

/** Design mode configuration for FoodBridge */
export const FOODBRIDGE_MODES = {
  minimal: {
    description: 'Clean, simple interface',
    threeD: false,
    default: true,
  },
  glass: {
    description: 'Glassmorphism styling',
    threeD: false,
    default: false,
  },
  cinematic: {
    description: 'Cinematic lighting and effects',
    threeD: false,
    default: false,
  },
  darkTech: {
    description: 'Dark theme with tech aesthetic',
    threeD: false,
    default: false,
  },
  '3d-spatial': {
    description: '3D spatial visualization',
    threeD: true,
    default: false,
  },
  dashboard: {
    description: 'Dashboard-focused layout',
    threeD: false,
    default: true,
  },
  education: {
    description: 'Education-focused layout',
    threeD: false,
    default: false,
  },
  environmental: {
    description: 'Environmental/themed layout',
    threeD: false,
    default: false,
  },
  medical: {
    description: 'Medical/themed layout',
    threeD: false,
    default: false,
  },
  fintech: {
    description: 'Fintech/themed layout',
    threeD: false,
    default: false,
  },
}

/** Get mode configuration */
export function getModeConfig(modeName) {
  return FOODBRIDGE_MODES[modeName] || FOODBRIDGE_MODES.minimal
}

/** Check if mode supports 3D */
export function modeSupports3D(modeName) {
  const config = getModeConfig(modeName)
  return config.threeD
}

/** Get all supported modes */
export function getAllModes() {
  return Object.keys(FOODBRIDGE_MODES)
}

/** Generate FoodBridge frontend configuration */
export function generateFoodbridgeConfig(options = {}) {
  const {
    framework = 'react',
    threeD = false,
    modes = ['minimal', 'glass', 'cinematic'],
    includeDemoControls = true,
  } = options

  // Resolve modes - filter to supported ones, apply defaults
  const resolvedModes = modes
    .map(m => {
      const config = getModeConfig(m)
      return { name: m, ...config }
    })
    .filter(m => !!getModeConfig(m.name))

  // Determine if 3D is enabled across any mode
  const any3D = resolvedModes.some(m => m.threeD)

  return {
    framework,
    threeD: threeD || any3D,
    modes: resolvedModes,
    includeDemoControls,
    apiBase: FOODBRIDGE_API.BASE,
    modeDescriptions: {
      LIVE: 'Use real backend API',
      DEMO: 'Use backend demo functionality',
      AUTO: 'Live backend when available; otherwise demo fallback',
    },
  }
}

/** Validate FoodBridge frontend setup */
export function validateFoodbridgeSetup() {
  const errors = []

  // Check if frontend directory exists
  const frontendDir = path.join(process.cwd(), 'frontend')
  if (!fs.existsSync(frontendDir)) {
    errors.push('Frontend directory not found. Run: npx vibe3d generate foodbridge --api ./openapi.json')
  }

  // Check for package.json
  const packageJsonPath = path.join(frontendDir, 'package.json')
  if (!fs.existsSync(packageJsonPath)) {
    errors.push('package.json not found in frontend directory')
  }

  // Check for vite.config.ts
  const viteConfigPath = path.join(frontendDir, 'vite.config.ts')
  if (!fs.existsSync(viteConfigPath)) {
    errors.push('vite.config.ts not found in frontend directory')
  }

  // Check for src directory
  const srcDir = path.join(frontendDir, 'src')
  if (!fs.existsSync(srcDir)) {
    errors.push('src/ directory not found in frontend directory')
  }

  return {
    valid: errors.length === 0,
    errors,
  }
}

/** Print FoodBridge integration status */
export function printStatus() {
  const setup = validateFoodbridgeSetup()
  const config = generateFoodbridgeConfig()

  console.log('Vibe3D: FoodBridge Integration Status')
  console.log('')

  console.log('  Framework:', config.framework)
  console.log('  3D Enabled:', config.threeD ? 'Yes' : 'No')
  console.log('  Modes:', config.modes.map(m => m.name).join(', '))
  console.log('')

  if (setup.valid) {
    console.log('  ✓ Frontend setup is valid')
  } else {
    console.log('  ✗ Frontend setup has issues:')
    setup.errors.forEach(e => console.log(`    - ${e}`))
  }

  console.log('')
  console.log('  API Base:', config.apiBase)
  console.log('  Mode Descriptions:')
  Object.entries(config.modeDescriptions).forEach(([mode, desc]) => {
    console.log(`    ${mode}: ${desc}`)
  })

  // Demo reset info
  console.log('')
  console.log('  Demo Reset:')
  if (config.includeDemoControls) {
    console.log('    - Enabled in DEMO mode')
    console.log('    - Disabled in LIVE mode (auth required)')
    console.log('    - Falls back in AUTO mode')
  } else {
    console.log('    - Disabled')
  }
}