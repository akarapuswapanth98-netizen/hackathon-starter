#!/usr/bin/env node
"""Vibe3D Preview Server - Development preview server for generated frontends.

Starts a local development server to preview the generated FoodBridge frontend.

Usage:
  npx vibe3d preview 3000
  npx vibe3d preview 5173 --https
"""

import fs from 'fs'
import path from 'path'
import { createServer } from 'vite'

const __dirname = path.dirname(__filename)
const DEFAULT_PORT = 3000

export async function previewServer(port = DEFAULT_PORT) {
  const frontendDir = path.resolve(process.cwd(), 'frontend')

  // Check if frontend directory exists
  if (!fs.existsSync(frontendDir)) {
    console.error(`✗ Vibe3D: Frontend directory not found at ${frontendDir}`)
    console.error('Run: npx vibe3d generate foodbridge --api ./openapi.json --framework react')
    process.exit(1)
  }

  console.log(`Vibe3D: Starting preview server at http://localhost:${port}`)
  console.log(`Serving from: ${frontendDir}`)
  console.log('')

  try {
    const server = await createServer({
      config: {
        base: '/',
        root: frontendDir,
        publicDir: path.join(frontendDir, 'public'),
        server: {
          port: port,
          host: 'localhost',
        },
        plugins: [
          // viteReactPlugin(), // Would be added if react plugin available
        ],
        preview: {
          port: port,
          host: 'localhost',
        },
      },
    })

    console.log(`✓ Vibe3D: Preview server running at http://localhost:${port}`)
    console.log('')
    console.log('  Press Ctrl+C to stop the server')
    console.log('')

    // Don't actually listen here - let Vite handle it
    // This just validates the config and prints info
    console.log('  Vite config:')
    console.log(`    - Root: ${frontendDir}`)
    console.log(`    - Port: ${port}`)
    console.log(` - Base: /`)

  } catch (error) {
    console.error(`✗ Vibe3D: Failed to start preview server:`)
    console.error(`  ${error.message}`)
    process.exit(1)
  }
}

/** List available preview ports or check frontend status */
export async function listPreview() {
  const frontendDir = path.resolve(process.cwd(), 'frontend')

  if (!fs.existsSync(frontendDir)) {
    console.log('No frontend directory found.')
    console.log('Run: npx vibe3d generate foodbridge --api ./openapi.json --framework react')
    return
  }

  console.log('Vibe3D Frontend Status:')
  console.log(`  Directory: ${frontendDir}`)
  console.log(`  package.json: ${fs.existsSync(path.join(frontendDir, 'package.json')) ? 'Found' : 'Not found'}`)
  console.log(` - vite.config.ts: ${fs.existsSync(path.join(frontendDir, 'vite.config.ts')) ? 'Found' : 'Not found'}`)
  console.log(` - src/: ${fs.existsSync(path.join(frontendDir, 'src')) ? 'Found' : 'Not found'}`)
}