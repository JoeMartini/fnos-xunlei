// Shared utilities for fnos-xunlei adapters.
//
// All three adapters (list/add/delete) delegate to the Python backend
// (xunlei_http.py) which handles the full auth chain and HTTP API calls.
// This keeps the auth logic in one place and avoids reimplementing it in JS.

import { execSync } from 'node:child_process';
import * as path from 'node:path';
import * as fs from 'node:fs';
import * as os from 'node:os';
import { CommandExecutionError, AuthRequiredError } from '@jackwener/opencli/errors';

// Locate the Python backend script.
// Search order:
// 1. Next to this adapter (clis/fnos-xunlei/scripts/)
// 2. XDG data dir: ~/.local/share/fnos-xunlei/
// 3. System-wide: /usr/local/share/fnos-xunlei/
export function resolveBackend() {
    const candidates = [
        path.join(import.meta.dirname, 'scripts', 'xunlei_http.py'),
        path.join(os.homedir(), '.local/share/fnos-xunlei/xunlei_http.py'),
        '/usr/local/share/fnos-xunlei/xunlei_http.py',
    ];

    for (const p of candidates) {
        if (fs.existsSync(p)) return p;
    }
    throw new CommandExecutionError(
        'xunlei_http.py not found. Install it to one of:\n  ' + candidates.join('\n  ')
    );
}

// Run the Python backend and return stdout.
// Throws CommandExecutionError on non-zero exit.
export function runBackend(scriptPath, args) {
    const cmdArgs = [scriptPath, ...args].map((a) => '"' + a.replace(/"/g, '\\"') + '"');
    const cmd = 'python3 ' + cmdArgs.join(' ');

    try {
        const stdout = execSync(cmd, {
            timeout: 30000,
            encoding: 'utf-8',
            stderr: 'pipe',
        });
        return stdout.trim();
    } catch (e) {
        const stderr = e.stderr || e.message || '';
        if (stderr.includes('fnos-token expired') || stderr.includes('Cannot obtain fnos-token')) {
            throw new AuthRequiredError('fnos-xunlei');
        }
        throw new CommandExecutionError(
            'Backend failed: ' + stderr.trim().substring(0, 200)
        );
    }
}
