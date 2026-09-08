import Link from 'next/link';
import { CalendarDays } from 'lucide-react';
export function Brand() { return <Link className="brand" href="/"><span className="brand-icon"><CalendarDays size={22}/></span>LiveTimetable<span className="beta">BETA</span></Link>; }
