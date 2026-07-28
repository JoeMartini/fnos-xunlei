/**
 * fnos-xunlei resume — Resume a paused download task via pure HTTP.
 *
 * Strategy: LOCAL (no browser session needed)
 */
import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';
import { resolveBackend, runBackend } from './_shared.js';

cli({
    site: 'fnos-xunlei',
    name: 'resume',
    access: 'write',
    description: '恢复已暂停的迅雷下载任务',
    strategy: Strategy.LOCAL,
    browser: false,
    args: [
        { name: 'taskId', type: 'string', required: true, positional: true, help: '任务 ID（从 list 命令获取）' },
    ],
    columns: ['status', 'taskId', 'message'],
    func: async (kwargs) => {
        const taskId = String(kwargs.taskId ?? '');
        if (!taskId) {
            throw new ArgumentError('taskId is required');
        }

        const script = resolveBackend();
        const stdout = runBackend(script, ['resume', taskId]);

        let result;
        try {
            result = JSON.parse(stdout);
        } catch {
            throw new CommandExecutionError('Failed to parse resume response from backend');
        }

        if (result.ok) {
            return [{ status: 'ok', taskId, message: 'Task resumed' }];
        }
        throw new CommandExecutionError(result.error || `Resume failed for task ${taskId}`);
    },
});
