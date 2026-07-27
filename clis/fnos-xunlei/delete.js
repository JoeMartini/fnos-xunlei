/**
 * fnos-xunlei delete — Delete a download task by ID via pure HTTP.
 *
 * Strategy: LOCAL (no browser session needed)
 */
import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';
import { resolveBackend, runBackend } from './_shared.js';

cli({
    site: 'fnos-xunlei',
    name: 'delete',
    access: 'write',
    description: '删除迅雷下载任务（可选同时删除本地文件）',
    strategy: Strategy.LOCAL,
    browser: false,
    args: [
        { name: 'taskId', type: 'string', required: true, positional: true, help: '任务 ID（从 list 命令获取）' },
        { name: 'keepFiles', type: 'bool', default: false, help: '不删除本地文件（默认删除）' },
    ],
    columns: ['status', 'taskId', 'message'],
    func: async (kwargs) => {
        const taskId = String(kwargs.taskId ?? '');
        if (!taskId) {
            throw new ArgumentError('taskId is required');
        }
        const keepFiles = kwargs.keepFiles === true || kwargs.keepFiles === 'true';

        const script = resolveBackend();
        const args = ['delete', taskId];
        if (keepFiles) args.push('--keep-files');

        const stdout = runBackend(script, args);

        let result;
        try {
            result = JSON.parse(stdout);
        } catch {
            throw new CommandExecutionError('Failed to parse delete response from backend');
        }

        if (result.ok) {
            return [{
                status: 'ok',
                taskId,
                message: keepFiles ? 'Task deleted (files kept)' : 'Task and files deleted',
            }];
        }
        throw new CommandExecutionError(result.error || `Delete failed for task ${taskId}`);
    },
});
