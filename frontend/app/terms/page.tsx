import Link from 'next/link';
import { Brand } from '@/components/brand';

export const metadata = { title: 'Terms | LiveTimetable' };

export default function Terms() {
  return <><header className="topbar"><Brand/><Link href="/">Home</Link></header><main style={{maxWidth: 780, margin: '48px auto', padding: '0 24px', lineHeight: 1.8}}>
    <h1>Using LiveTimetable</h1><p>Updated 11 September 2026.</p>
    <p>LiveTimetable helps students copy their selected programme and section from the configured college timetable into a separate Google Calendar. Use an account authorized to access that timetable.</p>
    <h2>Synchronization</h2><p>Automatic synchronization runs every six hours. You can request an immediate update with Sync now. Updates depend on the source timetable and Google services; unavailable services or an unreadable timetable can delay a sync. Check the official college timetable when a change is time-sensitive.</p>
    <h2>Your calendar</h2><p>The app updates its own timetable events, including room changes and cancellations. Direct edits to those events may be replaced by a later sync. Keep personal events in another calendar.</p>
    <h2>Stopping use</h2><p>You can revoke Google access whenever you choose. Your existing timetable calendar remains until you remove it in Google Calendar. See the <Link href="/privacy">privacy notice</Link> for stored data and deletion requests.</p>
    <h2>Support</h2><p>Use the app support email displayed on Google&apos;s consent screen for account or privacy requests. General software issues can be reported on the <a href="https://github.com/SlayerK15/CalendarApp/issues" target="_blank" rel="noreferrer">project&apos;s issue tracker</a>.</p>
    <p><Link href="/">Return to LiveTimetable</Link></p>
  </main></>;
}
