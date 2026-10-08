'use client';

import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { ChevronLeft, ChevronRight, Clock3, MapPin, X } from 'lucide-react';
import type { TimetableEvent } from '@/lib/api';
import { blocksForDay, dateKey, formatDay, shiftDate, weekStart } from '@/lib/calendar';

const subscribeToViewport = (callback: () => void) => {
  const query = window.matchMedia('(max-width: 650px)');
  query.addEventListener('change', callback);
  return () => query.removeEventListener('change', callback);
};
const mobileViewport = () => window.matchMedia('(max-width: 650px)').matches;
const serverViewport = () => false;
const hourLabel = (hour: number) => `${hour % 12 || 12} ${hour < 12 ? 'AM' : 'PM'}`;

export function TimetableCalendar({ events, timeZone = 'Asia/Kolkata' }: {
  events: TimetableEvent[]; timeZone?: string;
}) {
  const today = dateKey(new Date(), timeZone);
  const [selectedDate, setSelectedDate] = useState(today);
  const [chosenView, setChosenView] = useState<'week' | 'day' | null>(null);
  const mobile = useSyncExternalStore(subscribeToViewport, mobileViewport, serverViewport);
  const view = chosenView ?? (mobile ? 'day' : 'week');
  const [selectedEvent, setSelectedEvent] = useState<TimetableEvent | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (selectedEvent) dialog.current?.showModal();
  }, [selectedEvent]);
  const firstDay = view === 'week' ? weekStart(selectedDate) : selectedDate;
  const days = Array.from({ length: view === 'week' ? 7 : 1 }, (_, index) => shiftDate(firstDay, index));
  const columns = days.map(day => ({ day, blocks: blocksForDay(events, day, timeZone) }));
  const allBlocks = columns.flatMap(column => column.blocks);
  const startHour = Math.min(8, ...allBlocks.map(block => Math.floor(block.start / 60)));
  const endHour = Math.max(18, ...allBlocks.map(block => Math.ceil(block.end / 60)));
  const hours = Array.from({ length: endHour - startHour }, (_, index) => startHour + index);
  const time = (value: string) => new Intl.DateTimeFormat('en', { timeZone, hour: 'numeric', minute: '2-digit' }).format(new Date(value));
  const range = view === 'day'
    ? formatDay(firstDay, { weekday: 'long', month: 'short', day: 'numeric', year: 'numeric' })
    : `${formatDay(firstDay, { month: 'short', day: 'numeric', year: 'numeric' })} – ${formatDay(days[6], { month: 'short', day: 'numeric', year: 'numeric' })}`;
  function openEvent(event: TimetableEvent) {
    setSelectedEvent(event);
  }
  function move(direction: number) {
    setSelectedDate(shiftDate(selectedDate, direction * (view === 'week' ? 7 : 1)));
  }

  return <div className="timetable-calendar">
    <div className="calendar-toolbar">
      <div className="calendar-navigation">
        <button className="calendar-today" onClick={() => setSelectedDate(today)}>Today</button>
        <button className="calendar-arrow" aria-label={`Previous ${view}`} onClick={() => move(-1)}><ChevronLeft size={18}/></button>
        <button className="calendar-arrow" aria-label={`Next ${view}`} onClick={() => move(1)}><ChevronRight size={18}/></button>
      </div>
      <div className="calendar-view" role="group" aria-label="Calendar view">
        {(['week', 'day'] as const).map(option => <button key={option} aria-pressed={view === option} onClick={() => setChosenView(option)}>{option === 'week' ? 'Week' : 'Day'}</button>)}
      </div>
      <div className="calendar-range"><h3 aria-live="polite">{range}</h3><span>Times in {timeZone.replaceAll('_', ' ')}</span></div>
      <label className="calendar-date-picker">Go to date<input type="date" value={selectedDate} onChange={event => { if (/^\d{4}-\d{2}-\d{2}$/.test(event.target.value)) setSelectedDate(event.target.value); }}/></label>
    </div>
    {!allBlocks.length && <p className="calendar-empty" role="status">{events.length ? `No classes this ${view}. Choose another date to see your timetable.` : 'No synced classes yet. Your classes will appear here after a successful sync.'}</p>}
    <div className="calendar-scroll" role="region" aria-label={`${view === 'week' ? 'Weekly' : 'Daily'} class calendar. ${range}`} tabIndex={0}>
      <div className={`calendar-grid calendar-${view}`} style={{ gridTemplateColumns: `52px repeat(${days.length}, minmax(0, 1fr))` }}>
        <div className="calendar-corner" aria-hidden="true"/>
        {days.map(day => <div key={day} className={`calendar-day-heading ${day === today ? 'is-today' : ''}`}>
          <span>{formatDay(day, { weekday: 'short' })}</span><time dateTime={day} aria-current={day === today ? 'date' : undefined}>{formatDay(day, { day: 'numeric' })}</time>
        </div>)}
        <div className="calendar-hours" style={{ height: hours.length * 64 }} aria-hidden="true">
          {hours.map((hour, index) => <span key={hour} style={{ top: index * 64 }}>{hourLabel(hour)}</span>)}
        </div>
        {columns.map(({ day, blocks }) => <div className={`calendar-day-column ${day === today ? 'is-today' : ''}`} key={day} style={{ height: hours.length * 64 }}>
          {blocks.map(block => <button key={block.event.id}
            className={`calendar-event ${block.event.cancelled ? 'is-cancelled' : ''} ${block.end - block.start < 45 ? 'is-short' : ''}`}
            style={{ top: (block.start - startHour * 60) / 60 * 64, height: Math.max(18, (block.end - block.start) / 60 * 64 - 3), left: `calc(${block.lane / block.lanes * 100}% + 3px)`, width: `calc(${100 / block.lanes}% - 6px)` }}
            onClick={() => openEvent(block.event)}
            aria-label={`${block.event.cancelled ? 'Cancelled: ' : ''}${block.event.summary}, ${formatDay(day, { month: 'long', day: 'numeric' })}, ${time(block.event.start.dateTime)} to ${time(block.event.end.dateTime)}, ${block.event.location || 'No room specified'}`}
            title={`${block.event.summary}\n${time(block.event.start.dateTime)} – ${time(block.event.end.dateTime)}\n${block.event.location}${block.event.cancelled ? '\nCancelled' : ''}`}>
            <strong>{block.event.summary}</strong>
            <span>{time(block.event.start.dateTime)} – {time(block.event.end.dateTime)}</span>
            <small>{block.event.cancelled ? 'Cancelled' : block.event.location || 'No room specified'}</small>
          </button>)}
        </div>)}
      </div>
    </div>
    <p className="calendar-hint">Select a class for details. <span className="calendar-cancel-key"/> Cancelled</p>
    <dialog className="class-dialog" ref={dialog} aria-labelledby="class-dialog-title" onClose={() => setSelectedEvent(null)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      {selectedEvent && <div className="class-dialog-content">
        <button className="calendar-arrow dialog-close" aria-label="Close class details" onClick={() => dialog.current?.close()}><X size={20}/></button>
        <span className="mini-label">{selectedEvent.cancelled ? 'CANCELLED CLASS' : 'CLASS DETAILS'}</span>
        <h2 id="class-dialog-title">{selectedEvent.summary}</h2>
        <p>{formatDay(dateKey(selectedEvent.start.dateTime, timeZone), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p>
        <p><Clock3 size={16}/>{time(selectedEvent.start.dateTime)} – {time(selectedEvent.end.dateTime)} · {timeZone.replaceAll('_', ' ')}</p>
        <p><MapPin size={16}/>{selectedEvent.location || 'No room specified'}</p>
        {selectedEvent.cancelled && <p className="class-cancelled-note">This class has been cancelled.</p>}
        {selectedEvent.description && <div className="class-description">{selectedEvent.description}</div>}
      </div>}
    </dialog>
  </div>;
}
