import Link from 'next/link';
import { Brand } from '@/components/brand';

export const metadata = { title: 'Privacy | LiveTimetable' };

export default function Privacy() {
  return <><header className="topbar"><Brand/><Link href="/">Home</Link></header><main style={{maxWidth: 780, margin: '48px auto', padding: '0 24px', lineHeight: 1.8}}>
    <h1>Privacy notice</h1><p>Updated 11 September 2026.</p>
    <h2>What the app uses</h2><p>LiveTimetable uses your Google name and email to identify your account. With your permission, it reads the configured college timetable in Google Drive and creates and updates a separate College Timetable calendar. Calendar-list access helps recover a timetable calendar after an interrupted creation.</p>
    <h2>What is stored</h2><p>The app stores your account details, programme and section, selected timetable events, calendar identifier, synchronization status and Google authorization credentials. Google tokens are encrypted on the server. Session cookies are HttpOnly and use HTTPS in production; Google tokens are not stored in browser storage. Timetable workbook contents are processed in memory.</p>
    <h2>How information is used</h2><p>Google user data is used only to provide timetable synchronization. It is not sold or used for advertising or AI model training. Google processes your authorization and calendar requests. Render hosts the application and its PostgreSQL database. Operational logs may contain diagnostic context.</p>
    <h2>Retention and stopping access</h2><p>Account and selected timetable data remain while your connection is maintained. Sync history is removed after 30 days; expired login requests and sessions are removed during scheduled maintenance. Signing out ends your browser session but does not stop background synchronization.</p><p>You can revoke access in <a href="https://myaccount.google.com/connections" target="_blank" rel="noreferrer">your Google account connections</a>. Revoking access prevents future authorized Google requests. It does not automatically delete the app&apos;s stored account data or the calendar already created in Google Calendar. You can remove that calendar in Google Calendar settings.</p>
    <h2>Privacy and deletion requests</h2><p>Contact the support email shown on LiveTimetable&apos;s Google consent screen to request deletion of your stored account and timetable data or ask a privacy question. Do not include passwords or Google authorization tokens.</p>
    <p><Link href="/terms">Terms of use</Link> · <Link href="/">Return to LiveTimetable</Link></p>
  </main></>;
}
