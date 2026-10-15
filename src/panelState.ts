import type { Status } from './backend';

export const GAME_NOTE = 'Recording works on the Steam UI only. Close the game first.';

export interface PanelState {
    label: 'Record' | 'Stop';
    disabled: boolean;
    note: string | null;
}

export function panelState(status: Status): PanelState {
    switch (status.state) {
        case 'starting':
        case 'recording':
            return { label: 'Stop', disabled: false, note: null };
        case 'finishing':
            return { label: 'Stop', disabled: true, note: null };
        default:
            if (status.gameRunning) return { label: 'Record', disabled: true, note: GAME_NOTE };
            return { label: 'Record', disabled: false, note: status.error };
    }
}
