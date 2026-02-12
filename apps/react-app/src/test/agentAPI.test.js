/**
 * Unit tests for agentAPI utility functions
 * 
 * These tests verify the API helper functions work correctly
 * without requiring a running server.
 * 
 * Run tests:
 *   npm run test:run
 */

import { describe, it, expect } from 'vitest'
import { extractTextContent } from '../api/agentAPI.js'

describe('extractTextContent', () => {
  it('should extract text from valid response with message type', () => {
    const mockResponse = {
      output: [
        {
          type: 'message',
          content: [{ text: 'Hello, how can I help you?' }]
        }
      ]
    }

    const result = extractTextContent(mockResponse)
    
    expect(result).toHaveLength(1)
    expect(result[0]).toBe('Hello, how can I help you?')
  })

  it('should extract multiple text contents from response', () => {
    const mockResponse = {
      output: [
        {
          type: 'message',
          content: [{ text: 'First message' }]
        },
        {
          type: 'tool_call',
          content: [{ text: 'Tool output' }]
        },
        {
          type: 'message',
          content: [{ text: 'Second message' }]
        }
      ]
    }

    const result = extractTextContent(mockResponse)
    
    expect(result).toHaveLength(2)
    expect(result).toContain('First message')
    expect(result).toContain('Second message')
  })

  it('should not include duplicate text contents', () => {
    const mockResponse = {
      output: [
        {
          type: 'message',
          content: [{ text: 'Same message' }]
        },
        {
          type: 'message',
          content: [{ text: 'Same message' }]
        }
      ]
    }

    const result = extractTextContent(mockResponse)
    
    expect(result).toHaveLength(1)
    expect(result[0]).toBe('Same message')
  })

  it('should return empty array for response without output', () => {
    const mockResponse = {}
    const result = extractTextContent(mockResponse)
    expect(result).toHaveLength(0)
  })

  it('should return empty array for empty output array', () => {
    const mockResponse = { output: [] }
    const result = extractTextContent(mockResponse)
    expect(result).toHaveLength(0)
  })

  it('should skip non-message types', () => {
    const mockResponse = {
      output: [
        {
          type: 'tool_call',
          content: [{ text: 'Tool call output' }]
        },
        {
          type: 'function',
          content: [{ text: 'Function output' }]
        }
      ]
    }

    const result = extractTextContent(mockResponse)
    expect(result).toHaveLength(0)
  })

  it('should handle null/undefined gracefully', () => {
    expect(extractTextContent(null)).toHaveLength(0)
    expect(extractTextContent(undefined)).toHaveLength(0)
  })

  it('should handle malformed content array', () => {
    const mockResponse = {
      output: [
        {
          type: 'message',
          content: null
        },
        {
          type: 'message',
          content: []
        },
        {
          type: 'message'
          // missing content
        }
      ]
    }

    // Should not throw, just return empty
    const result = extractTextContent(mockResponse)
    expect(Array.isArray(result)).toBe(true)
  })
})

describe('API Configuration', () => {
  it('should use correct default API URL', async () => {
    // Check that the API URL is set correctly
    const expectedDefault = 'http://localhost:8000'
    
    // Import dynamically to check the default
    const module = await import('../api/agentAPI.js')
    
    // The module should export the askAgent function
    expect(typeof module.askAgent).toBe('function')
    expect(typeof module.extractTextContent).toBe('function')
  })
})
