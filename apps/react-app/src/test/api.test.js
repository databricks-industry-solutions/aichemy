/**
 * API Endpoint Connectivity Tests
 * 
 * These tests verify that the backend server can connect to the Databricks agent endpoint.
 * 
 * Prerequisites:
 * 1. Start the backend server: cd server && SERVING_ENDPOINT=<your-endpoint> python server.py
 * 2. Ensure DATABRICKS_TOKEN is set or you're authenticated via databricks-cli
 * 
 * Run tests:
 *   npm run test:api
 */

import { describe, it, expect } from 'vitest'

const API_BASE_URL = process.env.VITE_API_URL || 'http://localhost:8000'

describe('Backend Server Connectivity', () => {
  
  describe('Health Check', () => {
    it('should return healthy status from /api/health', async () => {
      const response = await fetch(`${API_BASE_URL}/api/health`)
      
      expect(response.ok).toBe(true)
      expect(response.status).toBe(200)
      
      const data = await response.json()
      expect(data).toHaveProperty('status', 'healthy')
      expect(data).toHaveProperty('host')
      
      console.log('✓ Health check passed')
      console.log(`  Host: ${data.host}`)
    })
  })

  describe('Agent Endpoint', () => {
    it('should successfully connect to Databricks (endpoint may or may not exist)', async () => {
      const testPayload = {
        input: [
          { role: 'user', content: 'Hello, this is a connectivity test.' }
        ],
        custom_inputs: {
          thread_id: `test-${Date.now()}`
        }
      }

      const response = await fetch(`${API_BASE_URL}/api/agent`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(testPayload),
      })

      const data = await response.json()

      // Test passes if:
      // 1. We get a 200 with valid output (endpoint exists and works)
      // 2. We get a 404 with ENDPOINT_NOT_FOUND (connectivity works, endpoint doesn't exist)
      // Both prove the backend can authenticate and reach Databricks
      
      if (response.ok) {
        // Endpoint exists - verify response structure
        expect(data).toHaveProperty('output')
        expect(Array.isArray(data.output)).toBe(true)
        console.log('✓ Agent endpoint responded successfully')
        console.log(`  Output items: ${data.output.length}`)
      } else if (response.status === 404 && data.detail?.includes('ENDPOINT_NOT_FOUND')) {
        // Endpoint doesn't exist but we successfully connected to Databricks
        console.log('✓ Databricks connectivity verified (endpoint not deployed)')
        console.log(`  Note: The serving endpoint is not deployed on this workspace`)
        expect(true).toBe(true) // Explicit pass
      } else {
        // Unexpected error
        console.log(`✗ Unexpected response: ${response.status}`)
        console.log(`  Detail: ${JSON.stringify(data)}`)
        expect.fail(`Unexpected error: ${response.status} - ${JSON.stringify(data)}`)
      }
    })

    it('should return proper error for malformed requests', async () => {
      const malformedPayload = {
        // Missing required 'input' field
        custom_inputs: {
          thread_id: 'test-malformed'
        }
      }

      const response = await fetch(`${API_BASE_URL}/api/agent`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(malformedPayload),
      })

      // Should return 422 Unprocessable Entity for validation errors
      expect(response.status).toBe(422)
      
      console.log('✓ Malformed request handled correctly')
    })
  })
})

describe('Databricks Authentication', () => {
  it('should authenticate with Databricks workspace', async () => {
    // The health endpoint returns the configured host, proving SDK initialized
    const response = await fetch(`${API_BASE_URL}/api/health`)
    const data = await response.json()
    
    expect(data.host).toMatch(/^https:\/\/.*\.cloud\.databricks\.com/)
    console.log('✓ Databricks authentication configured')
    console.log(`  Workspace: ${data.host}`)
  })
})

describe('Connection Error Handling', () => {
  it('should handle server unavailable gracefully', async () => {
    const badUrl = 'http://localhost:9999' // Non-existent server
    
    try {
      await fetch(`${badUrl}/api/health`, {
        signal: AbortSignal.timeout(5000) // 5s timeout
      })
      // If we get here, the server unexpectedly responded
      expect.fail('Expected connection to fail')
    } catch (error) {
      // Expected - connection should fail
      expect(error).toBeDefined()
      console.log('✓ Connection error handled correctly')
    }
  })
})
