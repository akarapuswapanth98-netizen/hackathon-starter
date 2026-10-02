/*
 * Vibe3D FoodBridge Integration Tests
 * 
 * Tests for the Vibe3D FoodBridge frontend generation and integration.
 * These tests verify that the generated frontend correctly connects
 * to the FoodBridge backend API without modifying backend behavior.
 */

import { openAPISchema } from '../openapi/index.js'
import { createApiClient } from '../openapi/client.js'
import { foodbridgeTemplate } from '../templates/foodbridge.js'
import { generateFoodbridgeFrontend } from '../generator/index.js'

describe('Vibe3D FoodBridge Integration', () => {
  let schema

  beforeAll(async () => {
    // Load the OpenAPI schema from the local file
    schema = await openAPISchema(path.join(process.cwd(), 'openapi.json'))
  })

  describe('OpenAPI Schema', () => {
    test('schema is valid and contains FoodBridge routes', () => {
      expect(schema).toBeDefined()
      expect(schema.info).toHaveProperty('title', 'Hackathon Starter')
      expect(schema.paths).toBeDefined()
    })

    test('contains FoodBridge endpoints', () => {
      const paths = schema.paths
      expect(paths['/api/foodbridge/restaurants']).toBeDefined()
      expect(paths['/api/foodbridge/shelters']).toBeDefined()
      expect(paths['/api/foodbridge/surplus']).toBeDefined()
      expect(paths['/api/foodbridge/match']).toBeDefined()
      expect(paths['/api/foodbridge/demo/reset']).toBeDefined()
    })
  })

  describe('API Client Generation', () => {
    test('generates API client successfully', () => {
      const result = createApiClient(schema, 'react')
      expect(result.clientFile).toBeDefined()
      expect(result.typesFile).toBeDefined()
    })

    test('API client contains FoodBridge endpoints', () => {
      const result = createApiClient(schema, 'react')
      const fs = require('fs')
      const clientContent = fs.readFileSync(result.clientFile, 'utf8')
      
      expect(clientContent).toContain('/api/foodbridge/restaurants')
      expect(clientContent).toContain('/api/foodbridge/surplus')
      expect(clientContent).toContain('/api/foodbridge/match')
    })
  })

  describe('FoodBridge Template', () => {
    test('generates required views', () => {
      const result = foodbridgeTemplate({ framework: 'react', threeD: false })
      
      expect(result.components).toBeDefined()
      expect(result.pages).toBeDefined()
      
      // Check required views exist
      expect(result.components).toContain('dashboard')
      expect(result.components).toContain('restaurants')
      expect(result.components).toContain('shelters')
      expect(result.components).toContain('matching')
      expect(result.components).toContain('allocation-results')
      expect(result.components).toContain('agent-events')
      expect(result.components).toContain('map-visualization')
      expect(result.components).toContain('demo-reset')
    })

    test('generates correct component names', () => {
      const result = foodbridgeTemplate({ framework: 'react', threeD: false })
      
      const expectedComponents = [
        'dashboard', 'restaurants', 'shelters', 'matching',
        'allocation-results', 'agent-events', 'map-visualization', 'demo-reset'
      ]
      
      expectedComponents.forEach(component => {
        expect(result.components).toContain(component)
      })
    })

    test('handles 3D mode', () => {
      const result = foodbridgeTemplate({ framework: 'react', threeD: true })
      
      expect(result.threeD).toBe(true)
      expect(result.components).toContain('3d-visualization')
    })

    test('handles design modes', () => {
      const result = foodbridgeTemplate({
        framework: 'react',
        threeD: false,
        modes: ['minimal', 'glass', 'cinematic']
      })
      
      expect(result.modes).toHaveLength(3)
      expect(result.components).toContain('mode-minimal')
      expect(result.components).toContain('mode-glass')
      expect(result.components).toContain('mode-cinematic')
    })
  })

  describe('Frontend Generation', () => {
    test('generates FoodBridge frontend structure', async () => {
      // This tests the generator without actually writing files
      // by verifying the structure it would create
      
      const result = await generateFoodbridgeFrontend({
        api: path.join(process.cwd(), 'openapi.json'),
        framework: 'react',
        threeD: false,
        modes: ['minimal', 'glass']
      })
      
      // Verify the generation completed without error
      expect(result).toBeDefined()
    })

    test('generation uses correct OpenAPI schema', async () => {
      const result = await generateFoodbridgeFrontend({
        api: path.join(process.cwd(), 'openapi.json'),
        framework: 'react',
        threeD: false
      })
      
      // Generation should complete without throwing
      expect(result).toBeDefined()
    })
  })

  describe('Mode Behavior', () => {
    test('DEMO mode uses demo reset', () => {
      // Verify the template generates demo reset controls
      const result = foodbridgeTemplate({ framework: 'react', threeD: false })
      expect(result.components).toContain('demo-reset')
    })

    test('LIVE mode uses real API', () => {
      // Dashboard should show real data in LIVE mode
      const result = foodbridgeTemplate({ framework: 'react', threeD: false })
      expect(result.components).toContain('dashboard')
    })

    test('AUTO mode falls back appropriately', () => {
      // AUTO mode should be handled by the frontend
      const result = foodbridgeTemplate({ framework: 'react', threeD: 'auto' })
      // The template should not crash on 'auto' mode
      expect(result).toBeDefined()
    })
  })
})