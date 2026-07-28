/**
 * fnos-xunlei list — List download tasks via pure HTTP (no browser).
 *
 * Calls the Python xunlei_http.py backend which handles the full
 * auth chain (fnos-token → pan_auth) and returns JSON.
 *
 * Strategy: LOCAL (no browser session needed)
 */
import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, EmptyResultError, CommandExecutionError } from '@jackwener/opencli/errors';
import { resolveBackend, runBackend } from './_shared.js';

cli({
    site: 'fnos-xunlei',
    name: 'list',
    access: 'read',
    description: '列出飞牛迅雷下载任务',
    strategy: Strategy.LOCAL,
    browser: false,
    args: [
        { name: 'limit', type: 'int', default: 100, help: '返回数量 (max 200)' },
    ],
    columns: ['index', 'id', 'name', 'phase', 'speed', 'progress'],
    func: async (kwargs) => {
        const limit = Number(kwargs.limit ?? 100);
        if (!Number.isInteger(limit) || limit <= 0) {
            throw new ArgumentError('limit must be a positive integer');
        }

        const script = resolveBackend();
        const stdout = runBackend(script, ['list', String(limit), '--json']);

        let tasks;
        try {
            tasks = JSON.parse(stdout);
        } catch {
            throw new CommandExecutionError('Failed to parse task list from backend');
        }

        if (!Array.isArray(tasks) || tasks.length === 0) {
            throw new EmptyResultError('fnos-xunlei list', 'No download tasks found');
        }

        return tasks.map((t, i) => ({
            index: i + 1,
            id: t.id || '',
            name: t.name || '',
            phase: t.phase || 'unknown',
            speed: t.speed_kb > 0 ? `${t.speed_kb}KB/s` : '-',
            progress: t.progress || '0',
        }));
    },
});
