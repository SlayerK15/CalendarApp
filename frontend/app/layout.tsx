import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'LiveTimetable · A little more in sync', description: 'Your college timetable, automatically connected to Google Calendar.', referrer: 'no-referrer' };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
