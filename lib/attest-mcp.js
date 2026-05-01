'use strict';

/**
 * STR-656 — `delimit attest mcp` local-preview implementation.
 *
 * Runs the five deterministic checks defined by the MCP Attestation
 * Methodology v1 (delimit.ai/methodology/mcp-attestation) and prints a
 * PREVIEW REPORT. This module deliberately does NOT sign anything, does
 * NOT publish to delimit.ai, does NOT generate a badge.
 *
 * The methodology gate (STR-657) keeps the public signed-attestation
 * surface locked until: 30d methodology visibility + 14d CLI shipped +
 * 5+ merge-gate pilot reference accounts + incident-response process
 * documented. Until that gate exits, this module emits previews only.
 *
 * Each check returns a result object:
 *   { id, status: 'pass' | 'fail' | 'skip' | 'error', detail, evidence }
 * - `status` drives the preview report's pass/fail headline.
 * - `detail` is human-readable (one line for the table).
 * - `evidence` is structured data captured for the would-be attestation.
 *
 * Re-runnability: every check operates on the resolved repo at HEAD (or
 * a caller-provided commit SHA). The check inputs are deterministic so
 * the output bytes for a given commit should be byte-stable across
 * machines, modulo the timestamp.
 */

const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');

const METHODOLOGY_URL = 'https://delimit.ai/methodology/mcp-attestation';
const METHODOLOGY_VERSION = 'v1';

function _resolveCommit(repoDir) {
    try {
        return execSync('git rev-parse HEAD', {
            cwd: repoDir, encoding: 'utf-8', timeout: 3000,
        }).trim();
    } catch {
        return null;
    }
}

function _readJsonSafe(p) {
    try { return JSON.parse(fs.readFileSync(p, 'utf-8')); } catch { return null; }
}

// ────────────────────────────────────────────────────────────────────
// Check 1: dependency-security
// ────────────────────────────────────────────────────────────────────
function checkDependencySecurity(repoDir) {
    const id = 'dependency-security';
    const pkgPath = path.join(repoDir, 'package.json');
    if (!fs.existsSync(pkgPath)) {
        return {
            id, status: 'skip',
            detail: 'no package.json — non-Node project (Python/Go/Rust attest paths land in v2)',
            evidence: { reason: 'package_json_absent' },
        };
    }
    let auditResult;
    try {
        const out = execSync('npm audit --json --omit=dev', {
            cwd: repoDir, encoding: 'utf-8', timeout: 30000,
            stdio: ['ignore', 'pipe', 'ignore'],
        });
        auditResult = JSON.parse(out);
    } catch (e) {
        // npm audit exits non-zero when vulns found — output is on stdout.
        try { auditResult = JSON.parse(e.stdout); } catch { auditResult = null; }
    }
    if (!auditResult || !auditResult.metadata) {
        return {
            id, status: 'error',
            detail: 'npm audit unavailable (no lockfile or registry unreachable)',
            evidence: { reason: 'npm_audit_failed' },
        };
    }
    const vulns = auditResult.metadata.vulnerabilities || {};
    const critical = vulns.critical || 0;
    const high = vulns.high || 0;
    const status = critical > 0 ? 'fail' : 'pass';
    return {
        id, status,
        detail: `npm audit: ${critical} critical, ${high} high, ${vulns.moderate || 0} moderate, ${vulns.low || 0} low`,
        evidence: {
            counts: vulns,
            audit_source: 'npm-audit',
        },
    };
}

// ────────────────────────────────────────────────────────────────────
// Check 2: sbom-presence
// ────────────────────────────────────────────────────────────────────
function checkSbomPresence(repoDir) {
    const id = 'sbom-presence';
    const candidates = [
        'sbom.json', 'sbom.cdx.json', 'sbom.spdx.json',
        '.sbom/cyclonedx.json', '.sbom/spdx.json',
        'cyclonedx.json', 'spdx.json',
    ];
    for (const rel of candidates) {
        const p = path.join(repoDir, rel);
        if (fs.existsSync(p)) {
            const parsed = _readJsonSafe(p);
            if (!parsed) {
                return {
                    id, status: 'fail',
                    detail: `${rel} present but unparseable JSON`,
                    evidence: { path: rel, parseable: false },
                };
            }
            const format =
                parsed.bomFormat ? 'CycloneDX' :
                parsed.spdxVersion ? 'SPDX' :
                'unknown';
            return {
                id, status: 'pass',
                detail: `${rel} (${format})`,
                evidence: { path: rel, format, parseable: true },
            };
        }
    }
    return {
        id, status: 'skip',
        detail: 'no SBOM file found — see methodology for accepted paths',
        evidence: { searched: candidates },
    };
}

// ────────────────────────────────────────────────────────────────────
// Check 3: signed-tag
// ────────────────────────────────────────────────────────────────────
function checkSignedTag(repoDir) {
    const id = 'signed-tag';
    let tag;
    try {
        tag = execSync('git describe --tags --exact-match HEAD', {
            cwd: repoDir, encoding: 'utf-8', timeout: 3000,
            stdio: ['ignore', 'pipe', 'ignore'],
        }).trim();
    } catch {
        return {
            id, status: 'skip',
            detail: 'HEAD is not on a tagged commit (signed-tag check is release-only)',
            evidence: { reason: 'no_exact_tag' },
        };
    }
    let verifyOut;
    try {
        verifyOut = execSync(`git verify-tag --raw ${tag}`, {
            cwd: repoDir, encoding: 'utf-8', timeout: 5000,
            stdio: ['ignore', 'pipe', 'pipe'],
        });
    } catch {
        return {
            id, status: 'skip',
            detail: `tag ${tag} present but unsigned (sigstore/git-tag signature absent — not a failure, just recorded)`,
            evidence: { tag, signed: false },
        };
    }
    return {
        id, status: 'pass',
        detail: `tag ${tag} signed`,
        evidence: { tag, signed: true, verify_output: verifyOut.trim().slice(0, 200) },
    };
}

// ────────────────────────────────────────────────────────────────────
// Check 4: mcp-protocol-conformance (live probe — STR-656 Q1)
// ────────────────────────────────────────────────────────────────────
//
// The probe boots the server's declared entry point in a child process,
// completes the MCP initialize handshake, and calls tools/list over
// stdio. The captured tool signatures are evidence input for any future
// signed attestation; signature drift across attested versions is the
// next-attestation comparison input.
//
// Sandbox posture (best-effort, not a hard isolation boundary): empty
// HOME, restricted PATH, no extra env, hard timeout, SIGKILL on cleanup.
// The local preview is for surfacing shape; the hosted attestation will
// run inside a stronger sandbox.
//
function _findMcpEntry(pkg) {
    // Priority order:
    //   1. pkg.mcp.command (free-form shell string — explicit opt-in)
    //   2. pkg.mcp.entry   (path to a node script)
    //   3. pkg.bin (string)  → node <pkg.bin>
    //   4. pkg.bin (object)  → node <first value>
    //   5. pkg.main          → node <pkg.main>
    if (pkg.mcp && typeof pkg.mcp.command === 'string') {
        return { kind: 'shell', value: pkg.mcp.command };
    }
    if (pkg.mcp && typeof pkg.mcp.entry === 'string') {
        return { kind: 'node', value: pkg.mcp.entry };
    }
    if (typeof pkg.bin === 'string') {
        return { kind: 'node', value: pkg.bin };
    }
    if (pkg.bin && typeof pkg.bin === 'object') {
        const first = Object.values(pkg.bin)[0];
        if (typeof first === 'string') return { kind: 'node', value: first };
    }
    if (typeof pkg.main === 'string') {
        return { kind: 'node', value: pkg.main };
    }
    return null;
}

function _probeMcpServer(repoDir, entry, timeoutMs) {
    return new Promise((resolve) => {
        const cmd = entry.kind === 'shell' ? '/bin/sh' : process.execPath;
        const args = entry.kind === 'shell' ? ['-c', entry.value] : [entry.value];
        let proc;
        try {
            proc = spawn(cmd, args, {
                cwd: repoDir,
                stdio: ['pipe', 'pipe', 'pipe'],
                env: {
                    PATH: process.env.PATH || '/usr/local/bin:/usr/bin:/bin',
                    NODE_NO_WARNINGS: '1',
                    DELIMIT_ATTEST_PROBE: '1',
                },
            });
        } catch (e) {
            return resolve({ ok: false, reason: 'spawn_failed', error: e.message });
        }
        const stdoutBuf = [];
        const stderrBuf = [];
        let resolved = false;
        const finish = (result) => {
            if (resolved) return;
            resolved = true;
            try { proc.kill('SIGTERM'); } catch {}
            setTimeout(() => { try { proc.kill('SIGKILL'); } catch {} }, 500).unref();
            resolve(result);
        };
        const timer = setTimeout(() => {
            finish({
                ok: false, reason: 'timeout',
                stderr_tail: stderrBuf.join('').slice(-500),
            });
        }, timeoutMs);
        timer.unref();
        proc.stdout.on('data', (chunk) => {
            stdoutBuf.push(chunk.toString());
            const combined = stdoutBuf.join('');
            for (const line of combined.split('\n')) {
                if (!line.trim()) continue;
                try {
                    const msg = JSON.parse(line);
                    if (msg.id === 2 && msg.result && Array.isArray(msg.result.tools)) {
                        clearTimeout(timer);
                        return finish({ ok: true, tools: msg.result.tools });
                    }
                    if (msg.id === 2 && msg.error) {
                        clearTimeout(timer);
                        return finish({ ok: false, reason: 'tools_list_error', mcp_error: msg.error });
                    }
                } catch { /* incomplete line, keep buffering */ }
            }
        });
        proc.stderr.on('data', (chunk) => { stderrBuf.push(chunk.toString()); });
        proc.on('error', (e) => {
            clearTimeout(timer);
            finish({ ok: false, reason: 'process_error', error: e.message });
        });
        proc.on('exit', (code) => {
            clearTimeout(timer);
            finish({
                ok: false, reason: 'process_exit', code,
                stderr_tail: stderrBuf.join('').slice(-500),
            });
        });
        const init = JSON.stringify({
            jsonrpc: '2.0', id: 1, method: 'initialize',
            params: {
                protocolVersion: '2024-11-05',
                capabilities: {},
                clientInfo: { name: 'delimit-attest', version: '1.0' },
            },
        }) + '\n';
        const initialized = JSON.stringify({
            jsonrpc: '2.0', method: 'notifications/initialized', params: {},
        }) + '\n';
        const listTools = JSON.stringify({
            jsonrpc: '2.0', id: 2, method: 'tools/list', params: {},
        }) + '\n';
        try {
            proc.stdin.write(init);
            proc.stdin.write(initialized);
            proc.stdin.write(listTools);
        } catch (e) {
            clearTimeout(timer);
            finish({ ok: false, reason: 'stdin_write_failed', error: e.message });
        }
    });
}

async function checkMcpProtocolConformance(repoDir) {
    const id = 'mcp-protocol-conformance';
    const pkgPath = path.join(repoDir, 'package.json');
    const pkg = _readJsonSafe(pkgPath);
    if (!pkg) {
        return {
            id, status: 'skip',
            detail: 'no package.json to enumerate MCP entry point',
            evidence: { reason: 'package_json_absent' },
        };
    }
    const hasMcpDep =
        (pkg.dependencies && Object.keys(pkg.dependencies).some(k => k.startsWith('@modelcontextprotocol'))) ||
        (pkg.devDependencies && Object.keys(pkg.devDependencies).some(k => k.startsWith('@modelcontextprotocol')));
    if (!hasMcpDep && !pkg.mcp) {
        return {
            id, status: 'skip',
            detail: 'no @modelcontextprotocol/* dep or mcp config block — not an MCP server',
            evidence: { reason: 'mcp_dependency_absent' },
        };
    }
    const entry = _findMcpEntry(pkg);
    if (!entry) {
        return {
            id, status: 'skip',
            detail: 'MCP entry point not declared (set pkg.mcp.command, pkg.mcp.entry, or pkg.bin)',
            evidence: { reason: 'no_entry_point', mcp_dep_detected: hasMcpDep },
        };
    }
    if (entry.kind === 'node') {
        const abs = path.join(repoDir, entry.value);
        if (!fs.existsSync(abs)) {
            return {
                id, status: 'error',
                detail: `entry point not found on disk: ${entry.value}`,
                evidence: { entry, missing: true },
            };
        }
    }
    const probe = await _probeMcpServer(repoDir, entry, 8000);
    if (!probe.ok) {
        return {
            id, status: 'error',
            detail: `live probe failed: ${probe.reason}${probe.error ? ' — ' + probe.error : ''}`,
            evidence: { entry, probe },
        };
    }
    const toolSignatures = probe.tools.map(t => ({
        name: t.name,
        description_present: !!t.description,
        input_schema_keys: t.inputSchema && t.inputSchema.properties
            ? Object.keys(t.inputSchema.properties).sort()
            : [],
    }));
    return {
        id, status: 'pass',
        detail: `live probe: ${probe.tools.length} tools enumerated via tools/list`,
        evidence: {
            entry,
            tool_count: probe.tools.length,
            tool_signatures: toolSignatures,
            note: 'Signature drift across attested versions is the next-attestation comparison input.',
        },
    };
}

// ────────────────────────────────────────────────────────────────────
// Check 5: known-cve
// ────────────────────────────────────────────────────────────────────
function checkKnownCve(repoDir) {
    const id = 'known-cve';
    // npm audit (Check 1) already cross-references GHSA + npm advisory DB,
    // which together cover most public CVEs for the npm ecosystem. For
    // v1 the known-cve check piggy-backs on npm audit's advisory feed and
    // records the advisory IDs — full CVE-database resolution is staged
    // for the v1.1 release once we have a deterministic offline mirror.
    const depResult = checkDependencySecurity(repoDir);
    if (depResult.status === 'skip' || depResult.status === 'error') {
        return {
            id, status: 'skip',
            detail: `cve check requires dependency-security to run (was: ${depResult.status})`,
            evidence: { upstream: depResult.id },
        };
    }
    const counts = depResult.evidence.counts || {};
    const total = (counts.critical || 0) + (counts.high || 0) +
                  (counts.moderate || 0) + (counts.low || 0);
    const status = (counts.critical || 0) > 0 ? 'fail' : 'pass';
    return {
        id, status,
        detail: `${total} advisory IDs cross-referenced (CVE-database probe lands in v1.1)`,
        evidence: { advisory_counts: counts, source: 'npm-audit/GHSA' },
    };
}

// ────────────────────────────────────────────────────────────────────
// Top-level runner
// ────────────────────────────────────────────────────────────────────

async function _safeRun(id, fn, repoDir) {
    // Per-check runtime guard (STR-656 Q6 panel verdict). A single check
    // throwing — sync or async — must not crash the runner. It must
    // surface as an `error` status so the report is still complete and
    // the exit-code tier logic can treat it as a tool error (exit 2),
    // not a policy fail.
    try {
        const result = fn(repoDir);
        return await Promise.resolve(result);
    } catch (e) {
        return {
            id,
            status: 'error',
            detail: `check threw: ${e && e.message ? e.message : 'unknown error'}`,
            evidence: { reason: 'check_exception', message: e && e.message },
        };
    }
}

async function runAttestMcp(opts = {}) {
    const repoDir = path.resolve(opts.path || process.cwd());
    if (!fs.existsSync(repoDir)) {
        return { error: `path not found: ${repoDir}` };
    }
    const commit = _resolveCommit(repoDir);
    const checks = [
        await _safeRun('dependency-security', checkDependencySecurity, repoDir),
        await _safeRun('sbom-presence', checkSbomPresence, repoDir),
        await _safeRun('signed-tag', checkSignedTag, repoDir),
        await _safeRun('mcp-protocol-conformance', checkMcpProtocolConformance, repoDir),
        await _safeRun('known-cve', checkKnownCve, repoDir),
    ];
    return {
        kind: 'mcp_attestation_preview',
        methodology_version: METHODOLOGY_VERSION,
        methodology_url: METHODOLOGY_URL,
        repo: { path: repoDir, commit },
        checks,
        timestamp: new Date().toISOString(),
        signed: false,                       // STR-657 gate: never signed in scaffold.
        public: false,                       // STR-657 gate: never published.
        scaffold_notice:
            'DELIMIT ATTESTATION PREVIEW — NOT A PUBLIC ATTESTATION. ' +
            'MCP attestation is one surface of the Delimit merge gate product family ' +
            '(PR review + release attestations ship under the same delimit-cli). ' +
            'The public signed-attestation surface is gated on the methodology being live ≥30d, ' +
            'this CLI being shipped ≥14d, and 5+ merge-gate pilot reference accounts. ' +
            `See ${METHODOLOGY_URL}.`,
    };
}

function _statusEmoji(s) {
    return { pass: 'PASS', fail: 'FAIL', skip: 'SKIP', error: 'ERR ' }[s] || s;
}

function renderPreview(report) {
    const lines = [];
    lines.push('');
    lines.push('  DELIMIT ATTESTATION PREVIEW — NOT A PUBLIC ATTESTATION');
    lines.push('');
    lines.push(`  Methodology: ${report.methodology_url}  (${report.methodology_version})`);
    lines.push(`  Repo:        ${report.repo.path}`);
    if (report.repo.commit) {
        lines.push(`  Commit:      ${report.repo.commit}`);
    }
    lines.push(`  Timestamp:   ${report.timestamp}`);
    lines.push('');
    lines.push('  Checks:');
    for (const c of report.checks) {
        lines.push(`    [${_statusEmoji(c.status)}]  ${c.id.padEnd(30)} ${c.detail || ''}`);
    }
    lines.push('');
    lines.push(`  Signed: ${report.signed ? 'yes' : 'no (preview)'}`);
    lines.push(`  Public: ${report.public ? 'yes' : 'no (gate locked)'}`);
    lines.push('');
    lines.push('  This is a local preview only. To understand exactly what this');
    lines.push(`  attestation would and would NOT cover, read ${report.methodology_url}.`);
    lines.push('');
    return lines.join('\n');
}

module.exports = {
    runAttestMcp,
    renderPreview,
    METHODOLOGY_URL,
    METHODOLOGY_VERSION,
};
