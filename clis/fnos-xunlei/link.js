/**
 * fnos-xunlei link — Get the original download URL (magnet/http) for a task.
 *
 * Equivalent to the "复制链接" (copy link) context menu action in the Xunlei UI.
 * Returns the original magnet or HTTP URL that was used to create the task.
 *
 * Strategy: LOCAL (no browser session needed)
 */
import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';
import { resolveBackend, runBackend } from './_shared.js';

cli({
    site: 'fnos-xunlei',
    name: 'link',
    access: 'read',
    description: '获取迅雷任务的原始下载链接（磁力/HTTP）',
    strategy: Strategy.LOCAL,
    browser: false,
    args: [
        { name: 'taskId', type: 'string', required: true, positional: true, help: '任务 ID（从 list 命令获取）' },
    ],
    columns: ['taskId', 'url'],
    func: async (kwargs) => {
        const taskId = String(kwargs.taskId ?? '');
        if (!taskId) {
            throw new ArgumentError('taskId is required');
        }

        const script = resolveBackend();
        const stdout = runBackend(script, ['link', taskId]);

        // The backend prints the URL directly (no JSON wrapper for success)
        // If it fails, it prints JSON with an error field to stderr and exits non-zero
        let url = stdout.trim();
        if (!url) {
            throw new CommandExecutionError('No URL returned for task');
        }

        // If stdout looks like JSON error, parse it
        if (url.startsWith('{')) {
            try {
                const err = JSON.parse(url);
                throw new CommandExecutionError(err.error || 'Failed to get task link');
            } catch (e) {
                if (e instanceof CommandExecutionError) throw e;
            }
        }

        return [{ taskId, url }];
    },
});
