'use client';
import { Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { ArrowRight, ArrowUpRight, CalendarDays, Check, CheckCheck, RefreshCw, ShieldCheck, Sparkles } from 'lucide-react';
import { Brand } from '@/components/brand';
import { api } from '@/lib/api';

function AuthError() {
  const params = useSearchParams();
  const reason = params.get('auth');
  if (!reason) return null;
  const message = reason === 'restart'
    ? 'Start your sign-in here. Click Connect with Google to continue.'
    : reason === 'expired'
      ? 'That sign-in link is no longer valid. Click Connect with Google to start again.'
      : 'Google sign-in was not completed. Click Connect with Google to try again.';
  return <div className="error" role="alert">{message}</div>;
}

export default function Home() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function connect() {
    setBusy(true); setError('');
    try { const result = await api<{url: string}>('auth/google/start', {}); location.assign(result.url); }
    catch (error) { setError((error as Error).message); setBusy(false); }
  }
  return <><header className="topbar"><Brand/><nav><a href="#how-it-works">How it works</a><a className="nav-sign" href="/dashboard">Your dashboard <ArrowUpRight size={15}/></a></nav></header>
    <main className="landing"><section className="hero"><div className="hero-copy"><span className="eyebrow"><span className="live-dot"/> ONE LESS THING TO KEEP TRACK OF</span><h1>Classes change.<br/>Your calendar<br/><em>keeps up.</em></h1><p>Your college timetable, connected to Google Calendar. Every class, room change, and cancellation — taken care of.</p><button className="primary large" onClick={connect} disabled={busy}><span className="google-g">G</span>{busy ? 'Connecting…' : 'Connect with Google'}<ArrowRight size={18}/></button><div className="fine"><ShieldCheck size={14}/> Your Google tokens stay securely on the server.</div>{error && <div className="error" role="alert">{error}</div>}<Suspense><AuthError/></Suspense><div className="hero-foot"><span className="tiny-icon"><CheckCheck size={16}/></span> Set it up once. Get on with your semester.</div></div>
    <div className="preview-wrap"><div className="floating-label"><Sparkles size={15}/> A little more in sync</div><div className="calendar-preview"><div className="preview-head"><div><span className="mini-label">YOUR WEEK, SORTED</span><h3>College Timetable</h3></div><span className="status"><span className="live-dot"/> In sync</span></div><div className="preview-date"><span>September 2026</span><span className="demo-tag">ILLUSTRATIVE PREVIEW</span></div><div className="week-grid"><div className="week-heading">MON<strong>7</strong></div><div className="week-heading">TUE<strong>8</strong></div><div className="week-heading selected">WED<strong>9</strong></div><div className="week-heading">THU<strong>10</strong></div><div className="week-heading">FRI<strong>11</strong></div>{['Maths II','Design Lab','Economics','Maths II','Design Lab','Physics','Studio','Physics','Economics','Studio'].map((title, i) => <div key={i} className={`demo-cell tone-${i % 3}`}><span>{i < 5 ? '09:00 – 10:00' : '11:00 – 12:00'}</span><strong>{title}</strong><small>{i === 2 ? 'Room 204' : `Room ${101 + i}`}</small></div>)}</div><div className="preview-bottom"><RefreshCw size={13}/> Changes from your timetable appear here automatically.</div></div><div className="update-card"><span className="update-check"><Check size={20}/></span><div><strong>Room changed? Already updated.</strong><p>Economics · Room 102 → Room 204</p></div><span className="now">just now</span></div><div className="preview-caption">Less checking spreadsheets. More being there.</div></div></section>
    <section className="benefits" id="how-it-works"><div className="section-intro"><span className="mini-label">FROM SPREADSHEET TO SCHEDULE</span><h2>Three steps. A calmer semester.</h2></div><div className="steps"><article><span className="step-icon"><ShieldCheck/></span><span className="step-number">01</span><h3>Connect your Google account</h3><p>Sign in securely. We create a separate College Timetable calendar for your classes.</p></article><article><span className="step-icon"><CalendarDays/></span><span className="step-number">02</span><h3>Find your programme & section</h3><p>Choose your class from the live spreadsheet. Only your schedule gets added.</p></article><article><span className="step-icon"><RefreshCw/></span><span className="step-number">03</span><h3>Let your calendar keep up</h3><p>Timetable changes update existing events, with a backup check every five minutes.</p></article></div></section><footer><Brand/><span>Built for busy students. Made to stay in sync.</span><a href="https://calendar.google.com" target="_blank" rel="noreferrer">Google Calendar <ArrowUpRight size={14}/></a></footer></main></>;
}
