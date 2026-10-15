import { describe, expect, it } from 'vitest';
import type { Status } from '../src/backend';
import { GAME_NOTE, panelState } from '../src/panelState';

const status = (patch: Partial<Status>): Status => ({
    state: 'idle', elapsed: 0, size: 0, file: null, error: null, gameRunning: false, ...patch,
});

describe('panelState', () => {
    it('offers Record when idle', () => {
        expect(panelState(status({}))).toEqual({ label: 'Record', disabled: false, note: null });
    });
    it('disables Record while a game runs', () => {
        expect(panelState(status({ gameRunning: true }))).toEqual({ label: 'Record', disabled: true, note: GAME_NOTE });
        expect(GAME_NOTE).toBe('Recording works on the Steam UI only. Close the game first.');
    });
    it('offers Stop while starting or recording, and waits while finishing', () => {
        expect(panelState(status({ state: 'starting' }))).toEqual({ label: 'Stop', disabled: false, note: null });
        expect(panelState(status({ state: 'recording' }))).toEqual({ label: 'Stop', disabled: false, note: null });
        expect(panelState(status({ state: 'finishing' }))).toEqual({ label: 'Stop', disabled: true, note: null });
    });
    it('shows the last error as the note', () => {
        expect(panelState(status({ error: 'Screen stream in use by DeckCast' })).note).toBe('Screen stream in use by DeckCast');
    });
});
