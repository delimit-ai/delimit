#!/usr/bin/env node
/**
 * Delimit™ Gemini Action Adapter
 * Implements Google Gemini Extensions interface
 */

const axios = require('axios');
const AGENT_URL = `http://127.0.0.1:${process.env.DELIMIT_AGENT_PORT || 7823}`;

class DelimitGeminiAction {
    constructor() {
        this.id = 'delimit-governance';
        this.version = '2.0.0';
    }
    
    /**
     * Gemini uses action handlers for extension points
     */
    async beforeCodeGeneration(request) {
        console.log('[DELIMIT GEMINI] Pre-generation validation...');
        
        try {
            const { prompt, context, model } = request;
            
            // Check if the request involves sensitive operations
            const response = await axios.post(`${AGENT_URL}/evaluate`, {
                action: 'gemini_generation',
                prompt: prompt,
                context: context,
                model: model || 'gemini-pro',
                tool: 'gemini'
            });
            
            if (response.data.action === 'block') {
                throw new Error(`[DELIMIT] Generation blocked: ${response.data.reason}`);
            }
            
            if (response.data.action === 'prompt') {
                console.warn(`[DELIMIT] Warning: ${response.data.message}`);
            }
            
            return request; // Pass through
        } catch (error) {
            if (error.message.includes('[DELIMIT]')) {
                throw error; // Re-throw governance blocks
            }
            console.warn('[DELIMIT GEMINI] Governance check failed:', error.message);
            return request; // Fail open
        }
    }
    
    async afterResponse(response) {
        console.log('[DELIMIT GEMINI] Processing response...');
        
        try {
            // Collect evidence
            await axios.post(`${AGENT_URL}/audit`, {
                action: 'gemini_response',
                response: {
                    model: response.model,
                    tokens: response.usage,
                    timestamp: new Date().toISOString()
                }
            });
        } catch (error) {
            // Silent fail for audit
        }
        
        return response;
    }
    
    // Gemini command handler (uses @ prefix)
    async handleCommand(command, args) {
        const commands = {
            '@governance': 'delimit status',
            '@audit': 'delimit audit',
            '@mode': 'delimit mode'
        };
        
        if (commands[command]) {
            const { execSync } = require('child_process');
            return execSync(commands[command]).toString();
        }
    }
}

// Export for Gemini
module.exports = new DelimitGeminiAction();

// Gemini registration (if available)
if (typeof registerExtension === 'function') {
    registerExtension(new DelimitGeminiAction());
}