import { callable } from '@decky/api';

export type RecorderState = 'idle' | 'starting' | 'recording' | 'finishing';

export interface Status {
    state: RecorderState;
    elapsed: number;
    size: number;
    file: string | null;
    error: string | null;
    gameRunning: boolean;
}

export interface Recording {
    name: string;
    size: number;
    duration: number | null;
    mtime: number;
}

export interface Result {
    ok: boolean;
    error: string | null;
}

export interface ServerState {
    on: boolean;
    url: string | null;
}

export const backend = {
    start: callable<[], Result>('start'),
    stop: callable<[], Result>('stop'),
    getStatus: callable<[], Status>('get_status'),
    listRecordings: callable<[], Recording[]>('list_recordings'),
    remove: callable<[name: string], boolean>('delete'),
    setGameRunning: callable<[running: boolean], void>('set_game_running'),
    setServer: callable<[on: boolean], ServerState>('set_server'),
    getSettings: callable<[], { server: boolean; url: string | null }>('get_settings'),
};
