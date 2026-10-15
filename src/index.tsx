import { addEventListener, definePlugin, removeEventListener, toaster } from '@decky/api';
import { Router, staticClasses } from '@decky/ui';
import { FaVideo } from 'react-icons/fa';
import { backend } from './backend';
import { Panel } from './components/Panel';
import { LOG_PREFIX, PLUGIN_NAME } from './constants';
import { formatSize } from './format';
import { createGameWatch } from './gameWatch';

const STOPPED: Record<string, string> = {
    game: 'Recording stopped: a game started',
    disk: 'Recording stopped: disk almost full',
    ended: 'Recording ended unexpectedly',
};

const toast = (body: string) => toaster.toast({ title: PLUGIN_NAME, body });

export default definePlugin(() => {
    const watch = createGameWatch({
        runningAppId: () => (Router.MainRunningApp?.appid ? String(Router.MainRunningApp.appid) : null),
        every: (fn, ms) => {
            const id = setInterval(fn, ms);
            return () => clearInterval(id);
        },
        report: (running) => backend.setGameRunning(running),
    });
    watch.start();
    // The starting toast also makes gamescope send frames: gpu-screen-recorder gives up without a first frame.
    const listeners: [string, (...args: never[]) => void][] = [
        ['recording_starting', () => toast('Recording started')],
        ['recording_finished', (name: string, size: number) => toast(`Saved ${name}, ${formatSize(size)}`)],
        ['recording_stopped', (reason: string) => toast(STOPPED[reason] ?? 'Recording stopped')],
        ['recording_error', (message: string) => toast(message)],
    ];
    const registered = listeners.map(([event, fn]) => [event, addEventListener(event, fn)] as const);
    console.log(`${LOG_PREFIX} loaded`);
    return {
        name: PLUGIN_NAME,
        titleView: <div className={staticClasses.Title}>{PLUGIN_NAME}</div>,
        content: <Panel />,
        icon: <FaVideo />,
        onDismount() {
            watch.stop();
            registered.forEach(([event, listener]) => removeEventListener(event, listener));
        },
    };
});
