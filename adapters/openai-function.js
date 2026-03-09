#!/usr/bin/env node
/**
 * Delimit™ OpenAI Function Adapter
 * Implements OpenAI Functions/Tools interface
 */

const axios = require('axios');
const AGENT_URL = `http://127.0.0.1:${process.env.DELIMIT_AGENT_PORT || 7823}`;

class DelimitOpenAIFunction {
    constructor() {
        this.name = 'delimit_governance_check';
        this.description = 'Check governance compliance for code operations';
    }
    
    /**
     * OpenAI Functions are called as tools
     */
    async execute(args) {
        console.log('[DELIMIT OPENAI] Function called with:', args);
        
        try {
            const { action, context } = args;
            
            // Validate the action
            const response = await axios.post(`${AGENT_URL}/evaluate`, {
                action: action || 'openai_function',
                context: context,
                tool: 'openai'
            });
            
            return {
                allowed: response.data.action !== 'block',
                action: response.data.action,
                message: response.data.message || 'Check complete',
                rule: response.data.rule
            };
        } catch (error) {
            console.warn('[DELIMIT OPENAI] Governance check failed:', error.message);
            return {
                allowed: true,
                message: 'Governance unavailable, proceeding with caution'
            };
        }
    }
    
    /**
     * OpenAI Plugins interface
     */
    async handleRequest(request) {
        const { method, path, body } = request;
        
        if (path === '/governance/check') {
            return await this.execute(body);
        }
        
        if (path === '/governance/status') {
            const { execSync } = require('child_process');
            const status = execSync('delimit status --json').toString();
            return JSON.parse(status);
        }
        
        if (path === '/governance/audit') {
            const { execSync } = require('child_process');
            const audit = execSync('delimit audit --json').toString();
            return JSON.parse(audit);
        }
        
        return { error: 'Unknown endpoint' };
    }
    
    /**
     * Tool definition for OpenAI
     */
    toToolDefinition() {
        return {
            type: 'function',
            function: {
                name: this.name,
                description: this.description,
                parameters: {
                    type: 'object',
                    properties: {
                        action: {
                            type: 'string',
                            description: 'The action to validate'
                        },
                        context: {
                            type: 'object',
                            description: 'Context for validation',
                            properties: {
                                code: { type: 'string' },
                                language: { type: 'string' },
                                file: { type: 'string' },
                                operation: { type: 'string' }
                            }
                        }
                    },
                    required: ['action']
                }
            }
        };
    }
}

// Export for OpenAI
module.exports = new DelimitOpenAIFunction();

// OpenAI registration (if available)
if (typeof registerFunction === 'function') {
    registerFunction(new DelimitOpenAIFunction());
}