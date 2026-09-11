'use client';
import { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, CalendarDays, CheckCircle2, Clock3, LogOut, RefreshCw } from 'lucide-react';
import { Brand } from '@/components/brand';
import { api, ApiError, Dashboard } from '@/lib/api';

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [name, setName] = useState('');
  const [options, setOptions] = useState<Record<string, string[]>>({});
  const [programme, setProgramme] = useState('');
  const [section, setSection] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reconnectNeeded, setReconnectNeeded] = useState(false);
  const [notice, setNotice] = useState('');
  const refresh = useCallback(async () => {
    try { setData(await api<Dashboard>('dashboard')); }
    catch (error) { if (error instanceof ApiError && error.status === 401) location.replace('/'); else setError((error as Error).message); }
  }, []);
  useEffect(() => {
    api<Dashboard>('dashboard').then(result => {
      setData(result);
      setProgramme(result.programme || '');
      setSection(result.section || '');
    }).catch(error => {
      if (error instanceof ApiError && error.status === 401) location.replace('/');
      else setError(error.message);
    });
    api<{name: string}>('me').then(user => setName(user.name.split(' ')[0])).catch(() => {});
    api<Record<string, string[]>>('options').then(setOptions).catch(error => {
      setError(error.message);
      setReconnectNeeded(error instanceof ApiError && error.code === 'google_reconnect_required');
    });

  }, [refresh]);
  useEffect(() => {
    const poll = () => { if (!document.hidden) void refresh(); };
    const interval = setInterval(poll, data?.sync_in_progress ? 10000 : 300000);
    document.addEventListener('visibilitychange', poll);
    return () => { clearInterval(interval); document.removeEventListener('visibilitychange', poll); };
  }, [refresh, data?.sync_in_progress]);
  async function reconnect() {
    setBusy(true);
    try { const result = await api<{url: string}>('auth/google/start', {}); location.assign(result.url); }
    catch (error) { setError((error as Error).message); setBusy(false); }
  }
  async function action(path: string, body: unknown = {}) {
    setBusy(true); setError(''); setNotice('');
    try { await api(path, body); setNotice('Sync requested. This page will update when it finishes.'); await refresh(); }
    catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  return <><header className="topbar"><Brand/><nav><span className="nav-sign">{name && `Hi, ${name}`}</span><button className="text-button" onClick={async () => { try { await api('auth/logout', {}); location.replace('/'); } catch (error) { setError((error as Error).message); } }}><LogOut size={16}/> Sign out</button></nav></header><main className="dashboard"><div className="dash-title"><div><span className="eyebrow">A LITTLE MORE IN SYNC</span><h1>Your timetable.</h1><p>Your week ahead, without the spreadsheet shuffle.</p></div><button className="secondary" disabled={!data?.active || busy} onClick={() => action('sync')}><RefreshCw size={16} className={busy ? 'spin' : ''}/> Sync now</button></div>{error && <div className="error" role="alert">{error}{reconnectNeeded && <div style={{marginTop: 12}}><button className="primary" disabled={busy} onClick={reconnect}>{busy ? 'Connecting…' : 'Reconnect Google'}</button><p>Google will ask for permission to view and download your Drive files. The app reads the configured timetable.</p></div>}</div>}{notice && <div className="notice" role="status">{notice}</div>}
      <div className="dash-layout"><aside><section className="panel"><span className="mini-label">MAKE IT YOURS</span><h2>Your class</h2><form onSubmit={event => { event.preventDefault(); void action('subscription', {programme, section}); }}><label htmlFor="programme">Programme</label><select id="programme" value={programme} onChange={event => { setProgramme(event.target.value); setSection(''); }} required><option value="">Select programme</option>{Object.keys(options).map(value => <option key={value}>{value}</option>)}</select><label htmlFor="section">Section</label><select id="section" value={section} onChange={event => setSection(event.target.value)} disabled={!programme} required><option value="">Select section</option>{(options[programme] || []).map(value => <option key={value}>{value}</option>)}</select><button className="primary full" disabled={busy || !programme || !section}>{data?.active ? 'Update selection' : 'Connect my timetable'}<ArrowUpRight size={17}/></button></form><p className="aside-note">Your classes go into a separate <strong>College Timetable</strong> calendar.</p></section><section className="panel sync-panel"><span className="mini-label">CONNECTION STATUS</span><div><CheckCircle2 size={17}/><span>Calendar</span><strong>{data?.calendar_id ? 'Connected' : 'Not connected'}</strong></div><div><RefreshCw size={17}/><span>Update mode</span><strong>{data?.sync_on_change ? (data?.watch_active ? 'Active' : 'Awaiting watch') : 'Scheduled'}</strong></div><div><Clock3 size={17}/><span>Automatic sync</span><strong>Every {Math.round((data?.sync_interval_seconds || 21600) / 3600)} hours</strong></div><p>Last sync: {data?.last_synced_at ? new Date(data.last_synced_at).toLocaleString() : 'Not yet synced'}</p></section></aside>
      <div><section className="panel schedule"><div className="schedule-title"><div><h2>{data?.active ? `${data.programme} · ${data.section}` : 'A fresh start for your schedule'}</h2><p>{data ? `${data.event_count} scheduled classes` : 'Loading your timetable…'}</p></div>{(data?.pending || data?.sync_in_progress) && <span className="status">{data?.sync_in_progress ? 'Syncing…' : 'Changes queued'}</span>}</div>{data?.last_error && <div className="error" role="alert">{data.last_error}</div>}{!data?.events.length ? <div className="empty"><span className="empty-icon"><CalendarDays size={30}/></span><h3>{data?.active ? 'Your first sync is on its way' : 'Your week belongs here'}</h3><p>{data?.active ? 'Classes will appear after the spreadsheet is read and your calendar is created.' : 'Select your programme and section to bring your classes into Google Calendar.'}</p></div> : <div className="event-list">{data.events.map(event => <article className={`event-row ${event.cancelled ? 'cancelled' : ''}`} key={event.id}><div className="event-date"><strong>{new Date(event.start.dateTime).toLocaleDateString('en', {day: '2-digit'})}</strong><span>{new Date(event.start.dateTime).toLocaleDateString('en', {month: 'short'})}</span></div><div className="event-detail"><h3>{event.summary}</h3><p>{event.location || 'No room specified'} {event.cancelled && <span className="cancel-badge">Cancelled</span>}</p></div><span className="event-time">{new Date(event.start.dateTime).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} – {new Date(event.end.dateTime).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></article>)}</div>}{data?.calendar_id && <a className="calendar-link" href={`https://calendar.google.com/calendar/u/0/r?cid=${encodeURIComponent(data.calendar_id)}`} target="_blank" rel="noreferrer">Open Google Calendar <ArrowUpRight size={15}/></a>}</section><section className="panel activity"><h2>Recent activity</h2>{data?.runs.length ? data.runs.map((run, index) => <div className="activity-row" key={index}><span className={`activity-dot ${run.status === 'failed' ? 'failed' : ''}`}/><div><strong>{run.status === 'unchanged' ? 'Everything is up to date' : run.status === 'success' ? 'Timetable synced' : run.status === 'running' ? 'Sync in progress' : 'Sync needs attention'}</strong><p>{run.message}</p></div><time>{new Date(run.at).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}</time></div>) : <p className="muted">Updates will appear here after your first sync.</p>}</section></div></div></main></>;
}
