import { describe, expect, it } from 'vitest';
import { createGameWatch } from '../src/gameWatch';

describe('createGameWatch', () => {
    it('reports once at start, then only changes, every 250 ms', async () => {
        let app: string | null = null;
        let tick = () => {};
        let interval = 0;
        let cleared = false;
        const reports: boolean[] = [];
        const watch = createGameWatch({
            runningAppId: () => app,
            every: (fn, ms) => ((tick = fn), (interval = ms), () => { cleared = true; }),
            report: async (running) => { reports.push(running); },
        });
        watch.start();
        expect(interval).toBe(250);
        tick();
        app = '1057090';
        tick();
        tick();
        app = null;
        tick();
        expect(reports).toEqual([false, true, false]);
        watch.stop();
        expect(cleared).toBe(true);
    });
    it('reports again when a report failed', async () => {
        let tick = () => {};
        const reports: boolean[] = [];
        let fail = true;
        const watch = createGameWatch({
            runningAppId: () => '1',
            every: (fn) => ((tick = fn), () => {}),
            report: async (running) => {
                reports.push(running);
                if (fail) throw new Error('backend not ready');
            },
        });
        watch.start();
        await Promise.resolve();
        await Promise.resolve();
        fail = false;
        tick();
        expect(reports).toEqual([true, true]);
    });
});
