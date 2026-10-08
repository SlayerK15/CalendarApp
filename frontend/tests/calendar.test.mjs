import test from 'node:test';
import assert from 'node:assert/strict';
import { dateKey, shiftDate, weekStart, blocksForDay } from '../lib/calendar.ts';

const zone = 'Asia/Kolkata';
const event = (id, start, end, cancelled = false) => ({ id, summary: id, location: 'Room 1', description: '', cancelled, start: { dateTime: start }, end: { dateTime: end } });

test('calendar groups by timetable timezone, including midnight and year boundaries', () => {
  assert.equal(dateKey('2026-09-29T20:00:00Z', zone), '2026-09-30');
  assert.equal(weekStart('2027-01-03'), '2026-12-28');
  assert.equal(weekStart('2026-09-28'), '2026-09-28');
  assert.equal(shiftDate('2028-02-28', 1), '2028-02-29');
  assert.equal(shiftDate('2026-12-31', 1), '2027-01-01');
});

test('positions class times correctly and excludes other dates', () => {
  const items = [event('one', '2026-09-30T09:15:00+05:30', '2026-09-30T10:30:00+05:30')];
  assert.deepEqual(blocksForDay(items, '2026-09-30', zone).map(({start,end}) => [start,end]), [[555,630]]);
  assert.equal(blocksForDay(items, '2026-09-29', zone).length, 0);
});

test('overlapping and cancelled classes get separate lanes; adjacent classes reuse lanes', () => {
  const items = [
    event('a', '2026-09-30T09:00:00+05:30', '2026-09-30T10:00:00+05:30'),
    event('b', '2026-09-30T09:30:00+05:30', '2026-09-30T11:00:00+05:30', true),
    event('c', '2026-09-30T10:00:00+05:30', '2026-09-30T11:30:00+05:30'),
    event('d', '2026-09-30T11:30:00+05:30', '2026-09-30T12:00:00+05:30'),
  ];
  const blocks = blocksForDay(items, '2026-09-30', zone);
  assert.deepEqual(blocks.map(({lane,lanes}) => [lane,lanes]), [[0,2],[1,2],[0,2],[0,1]]);
  assert.equal(blocks[1].event.cancelled, true);
});

test('overnight classes span both days without adding an empty midnight class', () => {
  const items = [event('late', '2026-09-30T23:00:00+05:30', '2026-10-01T01:00:00+05:30')];
  assert.deepEqual(blocksForDay(items, '2026-09-30', zone).map(({start,end}) => [start,end]), [[1380,1440]]);
  assert.deepEqual(blocksForDay(items, '2026-10-01', zone).map(({start,end}) => [start,end]), [[0,60]]);
  items[0].end.dateTime = '2026-10-01T00:00:00+05:30';
  assert.equal(blocksForDay(items, '2026-10-01', zone).length, 0);
});

test('invalid and reversed times are excluded', () => {
  assert.equal(blocksForDay([event('bad', 'invalid', 'invalid'), event('backwards', '2026-09-30T10:00:00Z', '2026-09-30T09:00:00Z')], '2026-09-30', zone).length, 0);
});
