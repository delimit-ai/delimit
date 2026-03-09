#!/usr/bin/env node
/**
 * Delimit™ xAI Grok Plugin Adapter
 * Implements xAI Plugin interface
 */

const axios = require('axios');
const AGENT_URL = `http://127.0.0.1:${process.env.DELIMIT_AGENT_PORT || 7823}`;

class DelimitXAIPlugin {
    constructor() {
        this.name = 'delimit-governance';
        this.version = '2.0.0';
        this.capabilities = ['code_validation', 'security_check', 'audit_logging'];
    }
    
    /**
     * xAI Plugins use hooks for different stages
     */
    async prePrompt(context) {
        console.log('[DELIMIT XAI] Pre-prompt validation...');
        
        try {
            const { prompt, session, user } = context;
            
            // Check for risky prompts
            const riskyPatterns = [
                /sudo/i,
                /rm\s+-rf/i,
                /password/i,
                /credential/i,
                /secret/i
            ];
            
            const isRisky = riskyPatterns.some(pattern => pattern.test(prompt));
            
            if (isRisky) {
                const response = await axios.post(`${AGENT_URL}/evaluate`, {
                    action: 'xai_prompt',
                    prompt: prompt,
                    riskLevel: 'high',
                    session: session,
                    tool: 'xai'
                });
                
                if (response.data.action === 'block') {
                    return {
                        block: true,
                        message: `[DELIMIT] Prompt blocked: ${response.data.reason}`
                    };
                }
                
                if (response.data.action === 'prompt') {
                    return {
                        warning: response.data.message
                    };
                }
            }
            
            return { allow: true };
        } catch (error) {
            console.warn('[DELIMIT XAI] Governance check failed:', error.message);
            return { allow: true }; // Fail open
        }
    }
    
    async postResponse(context) {
        console.log('[DELIMIT XAI] Post-response processing...');
        
        try {
            const { response, session, metrics } = context;
            
            // Collect evidence
            await axios.post(`${AGENT_URL}/audit`, {
                action: 'xai_response',
                session: session,
                metrics: metrics,
                timestamp: new Date().toISOString()
            });
            
            // Check for sensitive data in response
            const sensitivePatterns = [
                /\b[A-Z0-9]{20,}\b/g, // API keys
                /-----BEGIN.*KEY-----/g, // Private keys
                /Bearer\s+[A-Za-z0-9\-._~+\/]+=*/g // Bearer tokens
            ];
            
            for (const pattern of sensitivePatterns) {
                if (pattern.test(response)) {
                    console.warn('[DELIMIT XAI] ⚠️  Sensitive data detected in response');
                    // Could redact or block here
                }
            }
        } catch (error) {
            // Silent fail for audit
        }
        
        return context;
    }
    
    async validateCode(code, language) {
        console.log('[DELIMIT XAI] Validating code...');
        
        try {
            const response = await axios.post(`${AGENT_URL}/evaluate`, {
                action: 'code_validation',
                code: code,
                language: language,
                tool: 'xai'
            });
            
            return {
                valid: response.data.action !== 'block',
                issues: response.data.issues || [],
                message: response.data.message
            };
        } catch (error) {
            return { valid: true, message: 'Validation unavailable' };
        }
    }
    
    // xAI command interface
    async executeCommand(command, args) {
        const commands = {
            'governance': () => this.runCLI('status'),
            'audit': () => this.runCLI('audit'),
            'mode': () => this.runCLI('mode', args),
            'policy': () => this.runCLI('policy')
        };
        
        if (commands[command]) {
            return await commands[command]();
        }
        
        return `Unknown command: ${command}`;
    }
    
    runCLI(command, args = []) {
        const { execSync } = require('child_process');
        const cmd = `delimit ${command} ${args.join(' ')}`.trim();
        return execSync(cmd).toString();
    }
}

// Export for xAI
module.exports = new DelimitXAIPlugin();

// xAI registration
if (typeof registerPlugin === 'function') {
    registerPlugin(new DelimitXAIPlugin());
}