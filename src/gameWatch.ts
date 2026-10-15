export interface GameWatchDeps {
    runningAppId(): string | null;
    every(fn: () => void, ms: number): () => void;
    report(running: boolean): Promise<void>;
}

const POLL_MS = 250;

/** Tells the backend whether a game runs: recording is only safe on the Steam UI. */
export function createGameWatch(deps: GameWatchDeps) {
    let last: boolean | null = null;
    let stopTimer: (() => void) | null = null;
    const poll = () => {
        const running = deps.runningAppId() !== null;
        if (running === last) return;
        last = running;
        deps.report(running).catch((error) => {
            last = null; // try again on the next poll: the backend must never miss a running game
            console.warn('[showreel] could not report the running game', error);
        });
    };
    return {
        start(): void {
            stopTimer = deps.every(poll, POLL_MS);
            poll();
        },
        stop(): void {
            stopTimer?.();
            stopTimer = null;
            last = null;
        },
    };
}
