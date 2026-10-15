import { ButtonItem, ConfirmModal, Field, PanelSection, PanelSectionRow, showModal, ToggleField } from '@decky/ui';
import { useCallback, useEffect, useState } from 'react';
import { backend, Recording, ServerState, Status } from '../backend';
import { formatElapsed, formatSize } from '../format';
import { panelState } from '../panelState';

const IDLE: Status = { state: 'idle', elapsed: 0, size: 0, file: null, error: null, gameRunning: false };
const RECENT = 5;

export function Panel() {
    const [status, setStatus] = useState<Status>(IDLE);
    const [recordings, setRecordings] = useState<Recording[]>([]);
    const [server, setServer] = useState<ServerState>({ on: false, url: null });
    const [busy, setBusy] = useState(false);

    const refreshList = useCallback(() => {
        backend.listRecordings().then(setRecordings, () => {});
    }, []);

    useEffect(() => {
        let lastState = IDLE.state;
        const poll = () => backend.getStatus().then((next) => {
            if (lastState !== 'idle' && next.state === 'idle') refreshList();
            lastState = next.state;
            setStatus(next);
        }, () => {});
        poll();
        refreshList();
        backend.getSettings().then(({ server: on, url }) => setServer({ on, url }), () => {});
        const id = setInterval(poll, 1000);
        return () => clearInterval(id);
    }, [refreshList]);

    const view = panelState(status);
    const press = async () => {
        setBusy(true);
        try {
            const result = view.label === 'Record' ? await backend.start() : await backend.stop();
            if (!result.ok && result.error && result.error !== 'cancelled') setStatus({ ...status, error: result.error });
            setStatus(await backend.getStatus());
        } finally {
            setBusy(false);
        }
    };
    const recording = status.state === 'recording';
    const confirmDelete = (name: string) => showModal(
        <ConfirmModal strTitle={`Delete ${name}?`} strOKButtonText="Delete"
            onOK={() => void backend.remove(name).then(refreshList)} />,
    );

    return (
        <>
            <PanelSection>
                <PanelSectionRow>
                    <ButtonItem layout="below" disabled={view.disabled || busy} onClick={() => void press()}>
                        {view.label}
                    </ButtonItem>
                </PanelSectionRow>
                {recording && (
                    <PanelSectionRow>
                        <div>{formatElapsed(status.elapsed)} · {formatSize(status.size)}</div>
                    </PanelSectionRow>
                )}
                {view.note && <PanelSectionRow><div>{view.note}</div></PanelSectionRow>}
                <PanelSectionRow>
                    <ToggleField label="Download page" checked={server.on} description={server.on ? server.url ?? '' : undefined}
                        onChange={(on) => void backend.setServer(on).then(setServer)} />
                </PanelSectionRow>
            </PanelSection>
            {recordings.length > 0 && (
                <PanelSection title="Recent recordings">
                    {recordings.slice(0, RECENT).map((r) => (
                        <PanelSectionRow key={r.name}>
                            <Field label={r.name} description={[formatSize(r.size), r.duration ? formatElapsed(r.duration) : null]
                                .filter(Boolean).join(' · ')} bottomSeparator="none">
                                <ButtonItem layout="inline" onClick={() => confirmDelete(r.name)}>Delete</ButtonItem>
                            </Field>
                        </PanelSectionRow>
                    ))}
                </PanelSection>
            )}
        </>
    );
}
