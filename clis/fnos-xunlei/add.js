/**
 * fnos-xunlei add — Add a magnet download task via pure HTTP.
 *
 * Strategy: LOCAL (no browser session needed)
 */
import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';
import { resolveBackend, runBackend } from './_shared.js';

cli({
    site: 'fnos-xunlei',
    name: 'add',
    access: 'write',
    description: '添加磁力链接到飞牛迅雷下载',
    strategy: Strategy.LOCAL,
    browser: false,
    args: [
        { name: 'magnet', type: 'string', required: true, positional: true, help: '磁力链接 (magnet:?xt=...)' },
    ],
    columns: ['status', 'taskId', 'taskName'],
    func: async (kwargs) => {
        const magnet = String(kwargs.magnet ?? '');
        if (!magnet.startsWith('magnet:')) {
            throw new ArgumentError('magnet must start with "magnet:"');
        }

        const script = resolveBackend();
        const stdout = runBackend(script, ['add', magnet]);

        let task;
        try {
            task = JSON.parse(stdout);
        } catch {
            throw new CommandExecutionError('Failed to parse add response from backend');
        }

        if (task.id) {
            return [{ status: 'ok', taskId: task.id, taskName: task.name || magnet.substring(0, 60) }];
        }
        throw new CommandExecutionError(task.error || 'Task creation failed');
    },
});
