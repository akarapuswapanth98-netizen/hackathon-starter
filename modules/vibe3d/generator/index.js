#!/usr/bin/env node
"""Vibe3D FoodBridge Frontend Generator.

Generates a React frontend from the FoodBridge OpenAPI schema.
Consumes the existing backend API - never modifies it.

Usage:
  npx vibe3d generate foodbridge --api http://localhost:8000/openapi.json --framework react --3d
  npx vibe3d generate foodbridge --api ./openapi.json --framework react --no-3d
"""

import fs from 'fs'
import path from 'path'
import os from 'os'

import { openAPISchema } from '../openapi/index.js'
import { createApiClient } from '../openapi/client.js'
import { foodbridgeTemplate } from '../templates/foodbridge.js'

const TEMPLATES_DIR = path.join(path.dirname(__filename), 'templates')

/**
 * Generate FoodBridge frontend from OpenAPI schema
 * @param {Object} options - Generation options
 * @param {string} options.api - OpenAPI schema URL or file path
 * @param {string} options.framework - React/Vue/Svelte/Next/Astro/Vanilla
 * @param {boolean} options.threeD - Whether to include 3D visualization
 * @param {string[]} options.modes - Design modes to include
 */
export async function generateFoodbridgeFrontend(options) {
  const { api, framework = 'react', threeD = false, modes = ['minimal', 'glass', 'cinematic'] } = options

  console.log(`Vibe3D: Generating FoodBridge frontend for ${framework} ${threeD ? 'with 3D' : '2D only'}`)

  // 1. Fetch/parse OpenAPI schema
  console.log('  Fetching OpenAPI schema...')
  const schema = await openAPISchema(api)
  console.log(`  - Schema loaded: ${schema.info.title} v${schema.info.version}`)

  // 2. Generate API client and types
  console.log('  Generating API client and TypeScript types...')
  const clientResult = await createApiClient(schema, framework)
  console.log(`  - Client: ${clientResult.clientFile}`)
  console.log(`  - Types: ${clientResult.typesFile}`)

  // 3. Generate FoodBridge template
  console.log('  Generating FoodBridge views...')
  const templateResult = await foodbridgeTemplate(schema, framework, threeD, modes)
  console.log(`  - Views: ${templateResult.viewsGenerated.length} views`)
  templateResult.viewsGenerated.forEach(view => console.log(`    - ${view}`))

  // 4. Write files to frontend directory
  const frontendDir = path.resolve(process.cwd(), 'frontend')
  await writeFrontendFiles(frontendDir, templateResult, framework)

  console.log('')
  console.log('✓ Vibe3D: FoodBridge frontend generation complete!')
  console.log(`  Location: ${frontendDir}/src/`)
  console.log('')
  console.log('  Generated:')
  console.log(`  - src/api/client.ts       # API client`)
  console.log(`  - src/types/api-types.ts  # TypeScript types`)
  console.log(`  - src/components/         # FoodBridge components`)
  console.log(`  - src/pages/              # Page components`)
  console.log(`  - src/hooks/              # React hooks`)
  console.log('  - package.json            # Dependencies')
  console.log('')
  console.log('  Quick start:')
  console.log(`  cd frontend && npm install && npm run dev`)
  console.log('  Then visit: http://localhost:5173')
}

/**
 * Write generated files to the frontend directory
 * @param {string} frontendDir - Frontend root directory
 * @param {Object} templateResult - Template generation result
 * @param {string} framework - Framework type
 */
async function writeFrontendFiles(frontendDir, templateResult, framework) {
  // Ensure directories exist
  const srcDir = path.join(frontendDir, 'src')
  const componentsDir = path.join(srcDir, 'components')
  const pagesDir = path.join(srcDir, 'pages')
  const hooksDir = path.join(srcDir, 'hooks')
  const apiDir = path.join(srcDir, 'api')

  fs.mkdirSync(componentsDir, { recursive: true })
  fs.mkdirSync(pagesDir, { recursive: true })
  fs.mkdirSync(hooksDir, { recursive: true })
  fs.mkdirSync(apiDir, { recursive: true })

  // 1. Write package.json
  const packageJson = {
    name: 'hackathon-frontend',
    version: '0.1.0',
    type: 'module',
    scripts: {
      dev: 'vite dev',
      build: 'vite build',
      preview: 'vite preview',
    },
    dependencies: {
      react: '^18.3.0',
      'react-dom': '^18.3.0',
      'axios': '^1.7.0',
      'qrcode': '^1.5.0',
    },
    devDependencies: {
      'vite': '^5.4.0',
      'typescript': '^5.5.0',
      '@types/react': '^18.3.0',
      '@types/react-dom': '^18.3.0',
    },
  }

  fs.writeFileSync(path.join(frontendDir, 'package.json'), JSON.stringify(packageJson, null, 2))

  // 2. Write index.html (minimal)
  const indexHtml = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hackathon FoodBridge</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>`
  fs.writeFileSync(path.join(frontendDir, 'public', 'index.html'), indexHtml)

  // 3. Write main.jsx
  const mainJsx = `<import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'

const root = createRoot(document.getElementById('root'))
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)`

  fs.writeFileSync(path.join(srcDir, 'main.jsx'), mainJsx)

  // 4. Write App.jsx (composed from generated components)
  const appComponents = templateResult.components.map(c => {
    // Map component names to import paths
    const mapping = {
      dashboard: 'Dashboard',
      restaurants: 'Restaurants',
      shelters: 'Shelters',
      matching: 'Matching',
      allocationResults: 'AllocationResults',
      agentEvents: 'AgentEvents',
      mapVisualization: 'MapVisualization',
    }
    const Component = mapping[c] || c
    return `import ${Component} from './components/${c}.jsx'`
  })

  const appJsx = `<import React from 'react'
${appComponents.join('\n')}
import { useMode } from './hooks/useMode'

function App() {
  const { mode, setMode } = useMode()

  return (
    <div className="app">
      <header>
        <h1>Hackathon FoodBridge</h1>
        <mode-select mode={mode} onChange={setMode} />
      </header>
      <main>
        <nav>
          <nav-links />
        </nav>
        <section className="content">
          {mode === 'demo' ? (
            <demo-reset />
          ) : null}
          <page-container>
            {/* Dynamic page routing based on mode */}

            {/* Default to dashboard */}
            <${templateResult.viewsGenerated[0] || 'Dashboard'} />
          </page-container>
        </section>
      </main>
    </div>
  )
</div>`

  fs.writeFileSync(path.join(srcDir, 'App.jsx'), appJsx)

  // 4. Write package.json with dependencies
  const pkgDeps = threeD
    ? {
      ...packageJson.dependencies,
      'three': '^0.165.0',
      '@types/three': '^0.165.0',
      'gsap': '^3.12.0',
    }
    : packageJson.dependencies

  const pkgDevDeps = threeD
    ? {
      ...packageJson.devDependencies,
      // No extra dev deps for 3D
      ...packageJson.devDependencies,
    }
    : packageJson.devDeps

  const fullPackage = {
    ...packageJson,
    dependencies: {
      ...packageJson.dependencies,
      ...(threeD ? { three: '^0.165.0' } : {}),
    },
    devDependencies: {
      ...packageJson.devDependencies,
      ...(threeD ? {} : {}),
    },
  }

  fs.writeFileSync(path.join(frontendDir, 'package.json'), JSON.stringify(fullPackage, null, 2))

  // 5. Write vite.config.ts
  const viteConfig = `<import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { visualize } from 'vite-bundle-analyzer'

export default defineConfig({
  plugins: [
    react(),
    ...(${threeD ? ['visualize()'] : []}),
  ],
  base: '/',
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          three: threeD ? ['three'] : undefined,
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})`

  fs.writeFileSync(path.join(frontendDir, 'vite.config.ts'), viteConfig)

  // 6. Write .env.example
  const envExample = `VITE_API_URL=http://localhost:8000/api
# 3D_ENABLED=true
# VITE_MODE=minimal
# LIVE_DEMO_AUTO=auto`
  fs.writeFileSync(path.join(frontendDir, '.env.example'), envExample)

  // 7. Write template-specific component files
  for (const component of templateResult.components) {
    const componentPath = path.join(componentsDir, `${component}.jsx`)
    if (!fs.existsSync(componentPath)) {
      // Generate a basic component scaffold
      const componentContent = `<import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useMode } from '../hooks/useMode'

export const ${component.charAt(0).toUpperCase() + component.slice(1)} = () => {
  const navigate = useNavigate()
  const { mode } = useMode()

  return (
    <section
      className="page"
      aria-label="${component.replace(/([A-Z])/g, ' $1').titleCase()}
    >
      <h2>${component.replace(/([a-z])([A-Z])/g, '$1 $2').titleCase()}</h2>
      <p>Content for ${component} will be generated based on the FoodBridge API.</p>
      <p>Current mode: {mode === 'demo' ? 'DEMO' : mode === 'live' ? 'LIVE' : 'AUTO'}</p>
    </section>
  )`
      fs.writeFileSync(componentPath, componentContent)
    }
  }

  // 7. Write page components
  for (const page of templateResult.pages) {
    const pagePath = path.join(pagesDir, `${page}.jsx`)
    if (!fs.existsSync(pagePath)) {
      const pageContent = `<import React from 'react'
import { useMode } from '../hooks/useMode'
import { useQuery } from '@tanstack/react-query'
import { getSurpluses } from '../api/client'

export const ${page.charAt(0).toUpperCase() + page.slice(1)} = () => {
  const { mode } = useMode()
  const { data, isLoading, isError } = useQuery(
    ['foodbridge', page],
    () => fetch(`${import.meta.env.VITE_API_URL}/api/foodbridge/${page}`).then(r => r.json()),
    { enabled: mode !== 'demo' }
  )

  if (isLoading) return <p>Loading...</p>
  if (isError) return <p>Error loading data</p>

  return (
    <section
      className="page"
      aria-label="${page.replace(/([a-z])([A-Z])/g, '$1 $2').titleCase()}"
    >
      <h2>${page.replace(/([a-z])([A-Z])/g, '$1 $2').titleCase()}</h2>
      {data && data.success ? (
        <pre>{JSON.stringify(data, null, 2)}</pre>
      ) : null}
    </section>
  )`
      fs.writeFileSync(pagePath, pageContent)
    }
  }

  // 8. Write hooks
  const hooks = [
    'useMode.jsx',
    'useApiClient.jsx',
  ]

  for (const hook of hooks) {
    const hookPath = path.join(hooksDir, hook)
    if (!fs.existsSync(hookPath)) {
      const hookContent = `<import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export const useMode = () => {
  const [mode, setMode] = useState('auto')
  const [user, setUser] = useState(null)

  useEffect(() => {
    // Check for mode in localStorage or URL params
    const storedMode = localStorage.getItem('vibe3d_mode')
    if (storedMode) {
      setMode(storedMode)
    }
  }, [])

  return { mode, setMode, user }
}

export const useApiClient = () => {
  const [apiUrl, setApiUrl] = useState(import.meta.env.VITE_API_URL || 'http://localhost:8000/api')

  return { apiUrl, setApiUrl }
}`
      fs.writeFileSync(path.join(hooksDir, hook), hookContent)
  }
}

/**
 * FoodBridge template - generates the required views.
 * @param {Object} schema - OpenAPI schema
 * @param {string} framework - Framework type
 * @param {boolean} threeD - Whether 3D is enabled
 * @param {string[]} modes - Design modes
 * @returns {Object} - Generation result with component/page lists
 */
function foodbridgeTemplate(schema, framework, threeD, modes) {
  const components = []
  const pages = []

  // Required FoodBridge views (from specification)
  const requiredViews = [
    'dashboard',
    'restaurants',
    'shelters',
    'matching',
    'allocation-results',
    'agent-events',
    'map-visualization',
    'demo-reset',
  ]

  // Add components based on required views
  for (const view of requiredViews) {
    components.push(view)
    pages.push(view) // Each view is also a page
  }

  // Add extra components based on framework and modes
  if (threeD) {
    components.push('3d-visualization')
    modes.forEach(mode => {
      if (!components.includes(`mode-${mode}`)) {
        components.push(`mode-${mode}`)
      }
    })
  }

  // Determine design modes to include
  const activeModes = [...new Set(modes)]

  return {
    framework,
    threeD,
    modes: activeModes,
    components,
    pages,
    // Map view names to display names
    viewLabels: {
      dashboard: 'Dashboard',
      restaurants: 'Restaurants & Surplus',
      shelters: 'Shelters',
      matching: 'Matching',
      'allocation-results': 'Allocation Results',
      agent-events: 'Agent Workflow',
      map-visualization: 'Map Visualization',
      'demo-reset': 'Demo Controls',
    },
  }
}

/** Export the schema parser for CLI use */
export { openAPISchema } from '../openapi/index.js'
export { createApiClient } from '../openapi/client.js'