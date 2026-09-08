'use client';
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/api';
export default function Complete() {
  const started = useRef(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const ticket = new URLSearchParams(location.hash.slice(1)).get('ticket');
    history.replaceState(null, '', '/auth/complete');
    if (!ticket) { location.replace('/?auth=expired'); return; }
    api('auth/exchange', {ticket}).then(() => location.replace('/dashboard')).catch(error => setError(error.message));
  }, []);
  return <main className="auth-card"><h1>{error ? 'Let’s try that again.' : 'Connecting your calendar…'}</h1>{error ? <><p role="alert">{error}</p><Link className="primary" href="/">Back to sign in</Link></> : <p>Finishing your secure Google sign-in.</p>}</main>;
}
