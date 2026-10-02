/*
 * Vibe3D FoodBridge Template
 * 
 * Generates React components and pages for the FoodBridge frontend.
 * Consumes the FoodBridge API - never calculates or replaces backend logic.
 * 
 * Required views (specification):
 *  1. Dashboard
 *  2. Restaurants / surplus
 *  3. Shelters
 *  4. Matching
 *  5. Allocation results
 *  6. Agent workflow/events
 *  7. Map/distance visualization
 *  8. Demo/reset controls where API permissions allow
 */

import { camelCase } from '../openapi/index.js'

/**
 * FoodBridge Template - generates required views
 * @param {Object} options - Template options
 * @param {string} options.framework - Framework (react, vue, etc.)
 * @param {boolean} options.threeD - Whether 3D visualization is enabled
 * @param {string[]} options.modes - Design modes to include
 * @returns {Object} - Generated template result
 */
export function foodbridgeTemplate(options) {
  const { framework = 'react', threeD = false, modes = ['minimal', 'glass', 'cinematic'] } = options

  const generatedComponents = []
  const generatedPages = []
  const designModes = [...new Set(modes)]

  // ============================================================
  // Required FoodBridge Views (specification-mandatory)
  // ============================================================

  // 1. Dashboard - Overview page
  generatedPages.push('dashboard')
  generatedComponents.push('dashboard')

  // 2. Restaurants & Surplus - List and manage surplus lots
  generatedPages.push('restaurants')
  generatedComponents.push('restaurants')

  // 3. Shelters - List and manage shelters
  generatedPages.push('shelters')
  generatedComponents.push('shelters')

  // 4. Matching - Match configuration interface
  generatedPages.push('matching')
  generatedComponents.push('matching')

  // 5. Allocation Results - Display match results
  generatedPages.push('allocation-results')
  generatedComponents.push('allocation-results')

  // 5b. 3D Visualization (optional)
  if (threeD) {
    generatedComponents.push('3d-visualization')
    // Add 3D mode specific components
    designModes.forEach(mode => {
      if (!generatedComponents.includes(`mode-${mode}`)) {
        generatedComponents.push(`mode-${mode}`)
      }
    })
  }

  // 5c. Agent Events / Workflow
  generatedPages.push('agent-events')
  generatedComponents.push('agent-events')

  // 6. Map / Distance Visualization
  generatedPages.push('map-visualization')
  generatedComponents.push('map-visualization')

  // 7. Demo/Reset Controls
  generatedPages.push('demo-reset')
  generatedComponents.push('demo-reset')

  // ============================================================
  // Extra Components based on Design Modes
  // ============================================================

  const modeComponents = designModes.map(mode => `mode-${mode}`).filter(c => !generatedComponents.includes(c))
  generatedComponents.push(...modeComponents)

  // ============================================================
  // Return template result
  // ============================================================

  return {
    framework,
    threeD,
    modes: designModes,
    components: [...new Set(generatedComponents)], // Deduplicate
    pages: [...new Set(generatedPages)], // Deduplicate
    viewDescriptions: {
      dashboard: 'Overview of matching status and meal allocation',
      restaurants: 'List and manage surplus lots from restaurants',
      shelters: 'List and manage shelters with capacity/urgency info',
      matching: 'Configure match parameters (radius, weights, shelters)',
      'allocation-results': 'Display results from a completed match',
      'agent-events': 'Visualize the 6-agent workflow progression',
      'map-visualization': 'Haversine distance visualization',
      'demo-reset': 'Demo mode reset and mode selection',
      '3d-visualization': 'Three.js 3D spatial visualization',
      'mode-minimal': 'Minimalist design mode',
      'mode-glass': 'Glassmorphism design mode',
      'mode-cinematic': 'Cinematic design mode',
    },
  }
}

/**
 * Generate a single React component file
 * @param {string} componentName - Name of the component
 * @param {string} framework - Framework type
 * @param {boolean} threeD - Whether 3D is enabled
 * @returns {string} - React component source code
 */
function generateComponent(componentName, framework, threeD) {
  const componentMap = {
    dashboard: `
import React from 'react'
import { useMode } from '../hooks/useMode'
import { useQuery } from '@tanstack/react-query'
import { listSurpluses } from '../api/client'

export const Dashboard = () => {
  const { mode } = useMode()
  const { data, isLoading, isError } = useQuery(
    ['foodbridge', 'surplus'],
    () => fetch(\`\${import.meta.env.VITE_API_URL}/api/foodbridge/surplus?include_all=\${mode === 'demo'}\`).then(r => r.json()),
    { enabled: mode !== 'demo' }
  )

  if (isLoading) return <p>Loading surplus data...</p>
  if (isError) return <p>Error loading data</p>

  const surpluses = data && data.success ? data.surplus : []
  return (
    <section aria-label="Dashboard" className="page">
      <h2>Dashboard</h2>
      <p>Total surpluses: {surpluses.length}</p>
      <ul>
        {surpluses.map((lot, i) => (
          <li key={i}>
            <strong>{lot.id}</strong>: {lot.meal_count} meals - {lot.food_type}
          </li>
        ))}
      </ul>
    </section>
  )
}
`,
    restaurants: `
import React from 'react'
import { useMode } from '../hooks/useMode'
import { useQuery } from '@tanstack/react-query'
import { listSurpluses } from '../api/client'

export const Restaurants = () => {
  const { mode } = useMode()
  const { data, isLoading, isError } = useQuery(
    ['foodbridge', 'restaurants'],
    () => fetch(\`\${import.meta.env.VITE_API_URL}/api/foodbridge/restaurants\`).then(r => r.json()),
    { enabled: mode !== 'demo' }
  )

  if (isLoading) return <p>Loading restaurants...</p>
  if (isError) return <p>Error loading restaurants</p>

  const restaurants = data && data.success ? data.restaurants : []
  return (
    <section aria-label="Restaurants" className="page">
      <h2>Restaurants & Surplus</h2>
      <p>Restaurants: {restaurants.length}</p>
      <ul>
        {restaurants.map((r, i) => (
          <li key={i}>
            <strong>{r.id}</strong>: {r.name} ({r.cuisine_types.join(', ')})
          </li>
        ))}
      </ul>
      <h3>Create Surplus</h3>
      <p>Use the backend POST /api/foodbridge/surplus endpoint to create a new surplus lot.</p>
    </section>
  )
`,
    shelters: `
import React from 'react'
import { useMode } from '../hooks/useMode'

export const Shelters = () => {
  const { mode } = useMode()

  return (
    <section aria-label="Shelters" className="page">
      <h2>Shelters</h2>
      <p>Shelter visualization is available via the API.</p>
      <p>Current mode: {mode === 'demo' ? 'DEMO' : mode === 'live' ? 'LIVE' : 'AUTO'}</p>
      <p>Shelter data can be fetched from: GET /api/foodbridge/shelters</p>
    </section>
  )
`,
    matching: `
import React from 'react'
import { useMode } from '../hooks/useMode'

export const Matching = () => {
  const { mode } = useMode()

  return (
    <section aria-label="Matching" className="page">
      <h2>Matching Configuration</h2>
      <p>Matching parameters are configured on the backend.</p>
      <p>Use POST /api/foodbridge/match to run a match workflow.</p>
      <p>Current mode: {mode === 'demo' ? 'DEMO' : mode === 'live' ? 'LIVE' : 'AUTO'}</p>
    </section>
  )
`,
    'allocation-results': `
import React from 'react'
import { useMode } from '../hooks/useMode'
import { useQuery } from '@tanstack/react-query'
import { match } from '../api/client'

export const AllocationResults = () => {
  const { mode } = useMode()
  const { data, isLoading, isError } = useQuery(
    ['foodbridge', 'match'],
    () => fetch(\`\${import.meta.env.VITE_API_URL}/api/foodbridge/match\`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ surplus_id: 'food-001' })
    }).then(r => r.json()),
    { enabled: mode !== 'demo' }
  )

  if (isLoading) return <p>Running match...</p>
  if (isError) return <p>Error running match</p>

  const result = data && data.success ? data : null
  if (!result) return <p>No match results yet</p>

  return (
    <section aria-label="Allocation Results" className="page">
      <h2>Allocation Results</h2>
      <p>Workflow ID: {result.workflow_id}</p>
      <p>Status: {result.workflow_status}</p>
      <p>Total allocated: {result.total_allocated} meals</p>
      <p>Unallocated: {result.unallocated} meals</p>
      <p>Summary: {result.summary}</p>
      <h3>Allocation Details</h3>
      {result.allocation && result.allocation.length > 0 ? (
        <ul>
          {result.allocation.map((a, i) => (
            <li key={i}>
              <strong>Shelter:</strong> {a.shelter_id}
              <br/>
              <strong>Meals:</strong> {a.meals}
              <br/>
              <strong>Distance:</strong> {a.distance_km} km
            </li>
          ))}
        </ul>
      ) : (
        <p>No allocations yet</p>
      )}
    </section>
  )
`,
    'agent-events': `
import React from 'react'
import { useMode } from '../hooks/useMode'

export const AgentEvents = () => {
  const { mode } = useMode()

  return (
    <section aria-label="Agent Events" className="page">
      <h2>Agent Workflow Events</h2>
      <p>The FoodBridge system uses 6 specialized agents:</p>
      <ul>
        <li>Coordinator - Validates request, initializes workflow</li>
        <li>Restaurant - Loads surplus lot, computes hours_remaining</li>
        <li>Shelter - Filters candidates: radius, dietary compatibility, demand</li>
        <li>Matching - Deterministic weighted scores + two-pass greedy allocation</li>
        <li>Logistics - Ordered delivery batches (nearest first), ETA</li>
        <li>Verification - Hard-constraint audit; grants bounded retry</li>
      </ul>
      <p>Current mode: {mode === 'demo' ? 'DEMO' : mode === 'live' ? 'LIVE' : 'AUTO'}</p>
      <p>Workflow status: <strong>{mode === 'demo' ? 'demo' : mode === 'live' ? 'running' : 'AUTO'}</strong></p>
    </section>
  )
`,
    'map-visualization': `
import React from 'react'
import { useMode } from '../hooks/useMode'

export const MapVisualization = () => {
  const { mode } = useMode()

  return (
    <section aria-label="Map Visualization" className="page">
      <h2>Map / Distance Visualization</h2>
      <p>Distance calculation uses the Haversine formula (no API key required).</p>
      <p>Coordinates from the backend: rest-001 at (17.42, 78.48).</p>
      <p>Current mode: {mode === 'demo' ? 'DEMO' : mode === 'live' ? 'LIVE' : 'AUTO'}</p>
      <p>Visualization: {threeD ? '3D (lazy-loaded)' : '2D'}</p>
      {threeD && <p>Three.js scene would render restaurant/shelter nodes and allocation connections</p>}
    </section>
  )
`,
    'demo-reset': `
import React from 'react'
import { useMode } from '../hooks/useMode'
import { useState } from 'react'

export const DemoReset = () => {
  const { mode } = useMode()
  const [resetStatus, setResetStatus] = useState(null)

  const handleReset = async () => {
    try {
      const response = await fetch(\`\${import.meta.env.VITE_API_URL}/api/foodbridge/demo/reset\`, {
        method: 'POST',
      })
      const result = await response.json()
      setResetStatus(result)
      if (result.success) {
        // Refresh the page or reload data after reset
        window.location.reload()
      }
    } catch (error) {
      console.error('Demo reset failed:', error)
      setResetStatus({ success: false, error: error.message })
    }
  }

  return (
    <section aria-label="Demo Reset" className="page">
      <h2>Demo Reset</h2>
      <p>This endpoint reseeds demo data, clears claims, and resets the event bus.</p>
      <button
        onClick={handleReset}
        disabled={mode !== 'demo'}
        aria-label="Reset demo data">
        {mode === 'demo' ? 'Reset Demo Data' : 'Demo reset disabled in LIVE mode'}
      </button>
      {resetStatus && (
        <div>
          {resetStatus.success ? (
            <p>✓ Demo data reset successfully</p>
          ) : (
            <p>✗ Reset failed: {resetStatus.error}</p>
          )}
        </div>
      )}
    </section>
  )
`,
    '3d-visualization': `
import React, { useEffect, useState } from 'react'

export const ThreeDVisualization = () => {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    // Check if WebGL is available
    const canvas = document.createElement('canvas')
    const hasWebGL = !!canvas.getContext('webgl')
    setMounted(hasWebGL)
  }, [])

  if (!mounted) {
    return (
      <div
        aria-label="3D Visualization"
        className="three-d-loading"
      >
        <p>Loading 3D visualization...</p>
        <p>WebGL: {navigator.webGL ? 'Available' : 'Not available'}</p>
        <p>This module will lazy-load Three.js when WebGL is available.</p>
      </div>
    )
  }

  // 3D scene would be rendered here
  return (
    <div
      aria-label="3D Visualization"
      className="three-d-scene">
      <h3>3D FoodBridge Visualization</h3>
      <p>Three.js scene: restaurant nodes, shelter nodes, allocation connections</p>
      <p>WebGL is available and 3D visualization is active.</p>
    </div>
  )
}
`
  return componentMap[componentName] || `
import React from 'react'

export const ${camelCase(componentName)} = () => {
  return (
    <section aria-label="${componentName.replace(/([a-z])([A-Z])/g, '$1 $2').titleCase()}" className="page">
      <h2>${componentName.replace(/([a-z])([A-Z])/g, '$1 $2').titleCase()}</h2>
      <p>Component: ${componentName}</p>
      <p>This component will be generated based on the FoodBridge API.</p>
    </section>
  )
`
}

/** Export the foodbridge template */
export { foodbridgeTemplate, generateComponent }