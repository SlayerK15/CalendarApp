'use client';

import { useEffect, useState } from 'react';
import { Clock3 } from 'lucide-react';
import type { AccountNotice, NoticeCampaign } from '@/lib/api';

export function AccountRecoveryNotice({ notice, campaign, busy, onReconnect }: {
  notice?: AccountNotice | null;
  campaign?: NoticeCampaign | null;
  busy: boolean;
  onReconnect: () => void;
}) {
  const [clock, setClock] = useState(() => Date.now());
  const expiresAt = notice?.expires_at || campaign?.expires_at;
  const deadline = expiresAt ? Date.parse(expiresAt) : NaN;
  useEffect(() => {
    if (!Number.isFinite(deadline)) return;
    // Close at the deadline even if the tab never makes another API request.
    const timer = setTimeout(() => setClock(Date.now()), Math.max(0, deadline - Date.now()) + 1);
    return () => clearTimeout(timer);
  }, [deadline]);
  if (!expiresAt || !Number.isFinite(deadline) || clock >= deadline) return null;
  const expiry = new Date(expiresAt).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  return <aside className="account-notice" role="status" aria-live="polite" aria-label="Timetable connection notice">
    <span className="eyebrow"><Clock3 size={14}/> AUTOMATIC TIMETABLE UPDATES</span>
    <h2>{notice?.title || 'Account connection reminder'}</h2>
    {notice ? <>
      <p>{notice.message}</p>
      {notice.action === 'reconnect'
        ? <button className="primary" disabled={busy} onClick={onReconnect}>{busy ? 'Connecting…' : 'Reconnect Google'}</button>
        : <a className="primary" href="#class-selection">Choose your class</a>}
      <small>This note clears when your timetable is connected, or on {expiry}.</small>
    </> : campaign && <>
      <p>{campaign.remaining} of {campaign.total} affected accounts still need to connect. Their users see a note with the next step.</p>
      <small>This reminder closes when everyone is active, or on {expiry}.</small>
    </>}
  </aside>;
}
