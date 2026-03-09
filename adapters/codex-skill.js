#!/usr/bin/env node
/**
 * Delimit™ Codex Skill Adapter
 * Implements GitHub Codex "Skills" interface
 */

const axios = require('axios');
const AGENT_URL = `http://127.0.0.1:${process.env.DELIMIT_AGENT_PORT || 7823}`;

class DelimitCodexSkill {
    constructor() {
        this.name = 'delimit-governance';
        this.version = '2.0.0';
    }
    
    /**
     * Codex Skills use onBeforeSuggestion and onAfterAccept events
     */
    async onBeforeSuggestion(context) {
        console.log('[DELIMIT CODEX] Validating code suggestion...');
        
        try {
            const { code, language, file } = context;
            
            // Check governance rules
            const response = await axios.post(`${AGENT_URL}/evaluate`, {
                action: 'codex_suggestion',
                code: code,
                language: language,
                file: file,
                tool: 'codex'
            });
            
            if (response.data.action === 'block') {
                return {
                    allow: false,
                    message: `[DELIMIT] Code blocked: ${response.data.reason}`
                };
            }
            
            if (response.data.action === 'prompt') {
                return {
                    allow: true,
                    warning: response.data.message
                };
            }
            
            return { allow: true };
        } catch (error) {
            console.warn('[DELIMIT CODEX] Governance check failed:', error.message);
            return { allow: true }; // Fail open
        }
    }
    
    async onAfterAccept(context) {
        console.log('[DELIMIT CODEX] Recording accepted suggestion...');
        
        try {
            // Collect evidence
            await axios.post(`${AGENT_URL}/audit`, {
                action: 'codex_accept',
                context: context,
                timestamp: new Date().toISOString()
            });
        } catch (error) {
            // Silent fail for audit
        }
    }
    
    // Codex-specific command handler
    async handleCommand(command, args) {
        if (command === 'governance') {
            const { execSync } = require('child_process');
            return execSync('delimit status --verbose').toString();
        }
    }
}

// Export for Codex
if (typeof module !== 'undefined' && module.exports) {
    module.exports = new DelimitCodexSkill();
}

// Codex registration
if (typeof registerSkill === 'function') {
    registerSkill(new DelimitCodexSkill());
}