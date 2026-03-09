#!/usr/bin/env node
/**
 * Delimit™ Cursor Extension Adapter
 * Implements VSCode-style extension for Cursor
 */

const vscode = typeof acquireVsCodeApi !== 'undefined' ? acquireVsCodeApi() : null;
const axios = require('axios');
const AGENT_URL = `http://127.0.0.1:${process.env.DELIMIT_AGENT_PORT || 7823}`;

class DelimitCursorExtension {
    constructor() {
        this.extensionId = 'delimit.governance';
        this.version = '2.0.0';
    }
    
    /**
     * Extension activation
     */
    async activate(context) {
        console.log('[DELIMIT CURSOR] Extension activated');
        
        // Register commands
        this.registerCommands(context);
        
        // Register code action provider
        this.registerCodeActions(context);
        
        // Register diagnostics
        this.registerDiagnostics(context);
        
        return {
            extendMarkdownIt: (md) => this.extendMarkdown(md)
        };
    }
    
    registerCommands(context) {
        const commands = {
            'delimit.checkGovernance': async () => {
                const { execSync } = require('child_process');
                const result = execSync('delimit status --verbose').toString();
                this.showMessage(result);
            },
            'delimit.switchMode': async () => {
                const mode = await this.showQuickPick(['advisory', 'guarded', 'enforce']);
                if (mode) {
                    const { execSync } = require('child_process');
                    execSync(`delimit mode ${mode}`);
                    this.showMessage(`Switched to ${mode} mode`);
                }
            },
            'delimit.viewAudit': async () => {
                const { execSync } = require('child_process');
                const audit = execSync('delimit audit --tail 20').toString();
                this.showMessage(audit, 'Audit Log');
            }
        };
        
        Object.entries(commands).forEach(([cmd, handler]) => {
            if (vscode) {
                context.subscriptions.push(
                    vscode.commands.registerCommand(cmd, handler)
                );
            }
        });
    }
    
    registerCodeActions(context) {
        // Register code action provider for all languages
        const provider = {
            provideCodeActions: async (document, range, context) => {
                const actions = [];
                
                // Check if there are any governance issues
                const text = document.getText(range);
                const issues = await this.checkGovernance(text, document.languageId);
                
                if (issues.length > 0) {
                    actions.push({
                        title: '🛡️ Fix Governance Issues',
                        command: 'delimit.fixIssues',
                        arguments: [issues]
                    });
                }
                
                return actions;
            }
        };
        
        if (vscode) {
            context.subscriptions.push(
                vscode.languages.registerCodeActionsProvider('*', provider)
            );
        }
    }
    
    registerDiagnostics(context) {
        const diagnosticCollection = vscode ? 
            vscode.languages.createDiagnosticCollection('delimit') : null;
        
        // Watch for document changes
        if (vscode) {
            vscode.workspace.onDidChangeTextDocument(async (event) => {
                const document = event.document;
                const diagnostics = [];
                
                // Check governance
                const text = document.getText();
                const issues = await this.checkGovernance(text, document.languageId);
                
                issues.forEach(issue => {
                    diagnostics.push({
                        range: new vscode.Range(
                            issue.line || 0, 
                            issue.column || 0,
                            issue.line || 0,
                            issue.columnEnd || 100
                        ),
                        message: issue.message,
                        severity: issue.severity === 'error' ? 
                            vscode.DiagnosticSeverity.Error :
                            vscode.DiagnosticSeverity.Warning
                    });
                });
                
                diagnosticCollection.set(document.uri, diagnostics);
            });
        }
        
        context.subscriptions.push(diagnosticCollection);
    }
    
    async checkGovernance(code, language) {
        try {
            const response = await axios.post(`${AGENT_URL}/evaluate`, {
                action: 'cursor_validation',
                code: code,
                language: language,
                tool: 'cursor'
            });
            
            if (response.data.issues) {
                return response.data.issues;
            }
            
            return [];
        } catch (error) {
            return [];
        }
    }
    
    showMessage(message, title = 'Delimit') {
        if (vscode) {
            vscode.window.showInformationMessage(`${title}: ${message}`);
        } else {
            console.log(`[${title}] ${message}`);
        }
    }
    
    async showQuickPick(items) {
        if (vscode) {
            return await vscode.window.showQuickPick(items);
        }
        return items[0];
    }
    
    extendMarkdown(md) {
        // Add custom markdown rendering for governance info
        return md.use((md) => {
            md.renderer.rules.delimit_governance = (tokens, idx) => {
                return `<div class="delimit-governance">${tokens[idx].content}</div>`;
            };
        });
    }
    
    deactivate() {
        console.log('[DELIMIT CURSOR] Extension deactivated');
    }
}

// Export for Cursor/VSCode
if (typeof module !== 'undefined' && module.exports) {
    module.exports = new DelimitCursorExtension();
}

// VSCode activation
if (vscode) {
    exports.activate = (context) => new DelimitCursorExtension().activate(context);
    exports.deactivate = () => new DelimitCursorExtension().deactivate();
}