#!/usr/bin/env node
"""Vibe3D OpenAPI module - parsing, client generation, and type generation.

Handles OpenAPI schema fetching, parsing, and TypeScript client generation
for the Hackathon Toolkit V2 FoodBridge API.
"""

import fs from 'fs'
import path from 'path'
import axios from 'axios'
import yaml from 'yaml'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/**
 * Fetch OpenAPI schema from a URL or file path
 * @param {string} apiUrl - OpenAPI JSON/YAML URL or file path
 * @returns {Object} - Parsed OpenAPI schema
 */
export async function openAPISchema(apiUrl) {
  let response

  // Determine if it's a file path or URL
  if (path.isAbsolute(apiUrl) || apiUrl.startsWith('./') || apiUrl.startsWith('../')) {
    // It's a file path
    const fileContent = fs.readFileSync(apiUrl, 'utf8')
    const parsed = yaml.parse(fileContent)
    return parsed.openapi
      ? parsed  // Full OpenAPI document
      : { openapi: parsed, info: { title: 'FoodBridge', version: '0.1.0' } }
  } else {
    // It's a URL - fetch via HTTP
    response = await axios.get(apiUrl, {
      headers: {
        'Accept': 'application/json, application/yaml',
      },
    })

    const contentType = response.headers['content-type'] || ''
    if (contentType.includes('yaml') || apiUrl.endsWith('.yaml') || apiUrl.endsWith('.yml')) {
      const parsed = yaml.parse(response.data)
      return parsed.openapi ? parsed : { openapi: parsed, info: { title: 'FoodBridge', version: '0.1.0' } }
    } else {
      // JSON
      return response.data.openapi ? response.data : { openapi: response.data, info: { title: 'FoodBridge', version: '0.1.0' } }
    }
  }
}

/**
 * Generate TypeScript API client from OpenAPI schema
 * @param {Object} schema - Parsed OpenAPI schema
 * @param {string} framework - Framework type (react, vue, etc.)
 * @returns {Object} - Generation result with file paths
 */
export function createApiClient(schema, framework = 'react') {
  const clientFile = path.join(
    process.cwd(),
    'frontend',
    'src',
    'api',
    'generated.ts'
  )

  const typesFile = path.join(
    process.cwd(),
    'frontend',
    'src',
    'types',
    'api-types.ts'
  )

  // Extract FoodBridge routes from the schema
  const paths = schema.paths || {}

  // Generate TypeScript types from schemas
  const typeDefinitions = generateTypeDefinitions(schema.components)

  // Generate API client
  const clientCode = generateApiClientCode(paths, framework)

  // Write files
  const frontendDir = path.join(process.cwd(), 'frontend')

  fs.mkdirSync(path.join(frontendDir, 'src', 'api'), { recursive: true })
  fs.mkdirSync(path.join(frontendDir, 'src', 'types'), { recursive: true })

  fs.writeFileSync(clientFile, clientCode, 'utf8')
  fs.writeFileSync(typesFile, typeDefinitions, 'utf8')

  return {
    clientFile,
    typesFile,
    schemaSize: JSON.stringify(schema).length,
  }
}

/**
 * Generate TypeScript type definitions from OpenAPI schemas
 * @param {Object} components - OpenAPI components object
 * @returns {string} - TypeScript type definitions
 */
function generateTypeDefinitions(components) {
  if (!components) return '// No components defined\\n'

  const typeDefs = []

  // Add FoodBridge-specific types based on known API
  typeDefs.push('// FoodBridge API Types')
  typeDefs.push('') 

  // Core response types
  typeDefs.push('export interface AgentEvent {')
  typeDefs.push('  agent: string')
  typeDefs.push('  status: string')
  typeDefs.push('  detail: string')
  typeDefs.push('}')
  typeDefs.push('')

  typeDefs.push('export interface MatchResponse {')
  typeDefs.push('  success: boolean')
  typeDefs.push('  workflow_id: string')
  typeDefs.push('  workflow_status: MatchStatus')
  typeDefs.push('  allocation: Allocation[]')
  typeDefs.push('  total_allocated: number')
  typeDefs.push('  unallocated: number')
  typeDefs.push('  summary: string')
  typeDefs.push('  summary_source: string')
  typeDefs.push('  retry_count: number')
  typeDefs.push('  metadata: Metadata')
  typeDefs.push('  agent_events: AgentEvent[]')
  typeDefs.push('}')
  typeDefs.push('')

  typeDefs.push('export interface MatchStatus {')
  typeDefs.push('  completed: string')
  typeDefs.push('  failed: string')
  typeDefs.push('  timeout: string')
  typeDefs.push('}')
  typeDefs.push('')

  typeDefs.push('export interface Allocation {')
  typeDefs.push('  shelter_id: string')
  typeDefs.push('  meals: number')
  typeDefs.push('  distance_km: number')
  typeDefs.push('  score: number')
  typeDefs.push('  breakdown: Record<string, number>')
  typeDefs.push('}')
  typeDefs.push('')

  typeDefs.push('export interface Metadata {')
  typeDefs.push('  weights: number[]')
  typeDefs.push('  demo_mode: boolean')
  typeDefs.push('  llm_provider: string')
  typeDefs.push('  requested_radius_km: number')
  typeDefs.push('  max_retries: number')
  typeDefs.push('  duration_ms: number')
  typeDefs.push('  logistics: Record<string, unknown>')
  typeDefs.push('  surplus_status: string')
  typeDefs.push('  surplus_remaining: number')
  typeDefs.push('  error?: string')
  typeDefs.push('}')
  typeDefs.push('')

  // Request types
  typeDefs.push('// Request types')
  typeDefs.push('export interface MatchRequest {')
  typeDefs.push('  surplus_id?: string')
  typeDefs.push('  shelter_ids?: string[]')
  typeDefs.push('  requested_radius_km?: number')
  typeDefs.push('  options?: Record<string, unknown>')
  typeDefs.push('}')
  typeDefs.push('')

  typeDefs.push('export interface CreateSurplusRequest {')
  typeDefs.push('  restaurant_id: string')
  typeDefs.push('  meal_count: number')
  typeDefs.push('  food_type?: string')
  typeDefs.push('  dietary_tags?: string[]')
  typeDefs.push('  notes?: string')
  typeDefs.push('}')
  typeDefs.push('')

  // Enum for match status
  typeDefs.push('export type MatchStatus =')
  typeDefs.push('  | ' + '"completed"')
  typeDefs.push('  | ' + '"failed"')
  typeDefs.push('  | ' + '"timeout"')
  typeDefs.push('')

  return typeDefs.join('\\n')
}

/**
 * Generate API client code
 * @param {Object} paths - OpenAPI paths object
 * @param {string} framework - Framework type
 * @returns {string} - Generated client code
 */
function generateApiClientCode(paths, framework) {
  // FoodBridge-specific endpoints (we know the contract)
  const endpoints = [
    { method: 'GET', path: '/api/foodbridge/restaurants', name: 'listRestaurants' },
    { method: 'GET', path: '/api/foodbridge/shelters', name: 'listShelters' },
    { method: 'GET', path: '/api/foodbridge/surplus', name: 'listSurplus' },
    { method: 'POST', path: '/api/foodbridge/surplus', name: 'createSurplus' },
    { method: 'POST', path: '/api/foodbridge/match', name: 'match' },
    { method: 'GET', path: '/api/foodbridge/agents/events', name: 'listEvents' },
    { method: 'GET', path: '/api/foodbridge/demo/reset', name: 'demoReset' },
    { method: 'GET', path: '/openapi.json', name: 'getOpenAPI' },
  ]

  let code = `// Automatically generated by Vibe3D
// Do not edit manually - edits will be overwritten

import axios from 'axios'

/**
 * Base API client for Hackathon FoodBridge
 * 
 * Base URL is determined by VITE_API_URL environment variable,
 * falling back to http://localhost:8000/api
 */
const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

const api = axios.create({
  baseURL: apiBase,
  timeout: 30000,
  withCredentials: false,
})

export { api }`

  // Add each endpoint as a function
  for (const endpoint of endpoints) {
    const [method, route, name] = [endpoint.method, endpoint.path, endpoint.name]
    const pathParams = route.replace('/api/foodbridge/', '/')

    // Create function name from endpoint name
    const funcName = camelCase(name)

    code += `

/**
 * ${funcName}
 * Fetches data from the FoodBridge backend API
 * @param {Object} [params] - Query parameters (if GET)
 * @param {Object} [body] - Request body (if POST)
 * @returns {Promise<Object>} API response
 */
export async function ${funcName}(${funcName === 'demoReset' ? '' : ''}${funcName === 'listSurplus' ? ': { restaurant_id?: string; include_all?: boolean }' : ''}) {
  try {
    const url = '${route}'
    const options = { method: '${method}', url: url, baseURL: apiBase }

    ${method === 'GET' && !['listSurplus'].includes(name) ? 
      `const { data } = await api.get('${route}')` :
      method === 'GET' && ['listSurplus'].includes(name) ?
      `const { data: { success, data } = await api.get('/api/foodbridge/surplus', { params: ${funcName} === 'listSurplus' ? { restaurant_id, include_all } : {} })}` :
      `${method === 'POST' ? `const { data } = await api.post('${route}', body)` : ''}`
    }

    return data
  } catch (error) {
    console.error('API error in ${funcName}:', error)
    throw error
  }
}`
  }

  return code
}

/**
 * Camel case a string
 * @param {string} str - Input string
 * @returns {string} - Camel case string
 */
function camelCase(str) {
  return str
    .replace(/[-_]/g, ' ')
    .replace(/^\s+|\s+$/g, '')
    .split(' ')
    .map((word, index) =>
      index === 0 ? word.toLowerCase() : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
    )
    .join('')
}

// Export all functions
export {
  openAPISchema,
  createApiClient,
  generateTypeDefinitions,
  generateApiClientCode,
}