import type { TimetableEvent } from './api';

export function dateKey(value: Date | string, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(value));
  const part = (name: string) => parts.find(item => item.type === name)!.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function shiftDate(day: string, amount: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + amount);
  return date.toISOString().slice(0, 10);
}

export function weekStart(day: string) {
  const weekday = new Date(`${day}T12:00:00Z`).getUTCDay();
  return shiftDate(day, -((weekday + 6) % 7));
}

export function formatDay(day: string, options: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat('en', { ...options, timeZone: 'UTC' }).format(new Date(`${day}T12:00:00Z`));
}

function minutesAt(value: string, timeZone: string) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(value));
  return Number(parts.find(p => p.type === 'hour')!.value) * 60 + Number(parts.find(p => p.type === 'minute')!.value);
}

export type CalendarBlock = { event: TimetableEvent; start: number; end: number; lane: number; lanes: number };

export function blocksForDay(events: TimetableEvent[], day: string, timeZone: string): CalendarBlock[] {
  const blocks = events.flatMap(event => {
    if (!Number.isFinite(Date.parse(event.start.dateTime)) || !Number.isFinite(Date.parse(event.end.dateTime)) ||
        Date.parse(event.end.dateTime) <= Date.parse(event.start.dateTime)) return [];
    const first = dateKey(event.start.dateTime, timeZone);
    const last = dateKey(event.end.dateTime, timeZone);
    if (day < first || day > last) return [];
    const start = day === first ? minutesAt(event.start.dateTime, timeZone) : 0;
    const end = day === last ? minutesAt(event.end.dateTime, timeZone) : 1440;
    return end > start ? [{ event, start, end, lane: 0, lanes: 1 }] : [];
  }).sort((a, b) => a.start - b.start || b.end - a.end || a.event.id.localeCompare(b.event.id));

  // Assign a column to each overlapping class, including chained overlaps.
  let group: CalendarBlock[] = [];
  let ends: number[] = [];
  let groupEnd = -1;
  const finish = () => { for (const block of group) block.lanes = ends.length; };
  for (const block of blocks) {
    if (block.start >= groupEnd) {
      finish(); group = []; ends = []; groupEnd = -1;
    }
    let lane = ends.findIndex(end => end <= block.start);
    if (lane === -1) lane = ends.length;
    ends[lane] = block.end;
    block.lane = lane;
    group.push(block);
    groupEnd = Math.max(groupEnd, block.end);
  }
  finish();
  return blocks;
}
