'use strict';

/**
 * STR-656 Q5 — minimal telemetry counter for `delimit attest <kind>`.
 *
 * What this records (one JSONL line per invocation):
 *   timestamp, kind, outcome, methodology_version, check_summary
 *
 * What this does NOT record:
 *   - repo path, commit SHA, file contents, dependency names, tool names
 *   - any user-identifying data
 *
 * Records land in ~/.delimit/telemetry/attest-<kind>.jsonl. They are local
 * by default — this module does NOT phone home. The path is documented so
 * a future opt-in upload can read the same file without changing the CLI.
 *
 * Kill switch: `DELIMIT_NO_TELEMETRY=1` disables all writes. Honored across
 * the Delimit CLI; this module is one of several call sites.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const TELEMETRY_DIR = path.join(os.homedir(), '.delimit', 'telemetry');

function _isDisabled() {
    const v = process.env.DELIMIT_NO_TELEMETRY;
    return v === '1' || v === 'true' || v === 'yes';
}

function recordTelemetry(record) {
    if (_isDisabled()) return;
    const line = {
        ts: new Date().toISOString(),
        ...record,
    };
    try {
        fs.mkdirSync(TELEMETRY_DIR, { recursive: true });
        const file = path.join(TELEMETRY_DIR, `attest-${record.kind || 'unknown'}.jsonl`);
        fs.appendFileSync(file, JSON.stringify(line) + '\n');
    } catch {
        // Telemetry must never affect the user's exit code or output.
        // Swallow all errors (EROFS, EACCES, ENOSPC, etc.) silently.
    }
}

module.exports = { recordTelemetry, TELEMETRY_DIR };
