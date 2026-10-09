import React, { useState } from 'react';
import { AlertTriangle, Ban } from 'lucide-react';
import { cn } from '../lib/utils';

// How each point prediction was produced (backend `projection_source`)
export const SOURCE_LABELS = {
  sleeper: 'Sleeper projection',
  'sleeper+model': 'Sleeper projection, model-adjusted',
  model: 'Model estimate (no Sleeper projection)',
};

const QUESTIONABLE = new Set(['Questionable', 'Doubtful']);
const OUT = new Set(['Out', 'IR', 'PUP', 'Sus', 'NA']);

const kickoffFormat = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  hour: 'numeric',
  minute: '2-digit',
});

export function matchupLabel(context) {
  if (!context?.opponent) return null;
  return `${context.is_home ? 'vs' : '@'} ${context.opponent}`;
}

export function kickoffLabel(context) {
  if (!context?.kickoff) return null;
  const date = new Date(context.kickoff);
  return Number.isNaN(date.getTime()) ? null : kickoffFormat.format(date);
}

/** Injury status chip: status color on the icon only, label in ink. */
export function InjuryChip({ status }) {
  if (!status || (!QUESTIONABLE.has(status) && !OUT.has(status))) return null;
  const out = OUT.has(status);
  const Icon = out ? Ban : AlertTriangle;
  return (
    <span className="inline-flex items-center gap-1 rounded-sm bg-turf/60 px-1.5 py-0.5 text-xs font-medium text-chalk">
      <Icon aria-hidden="true" className={cn('h-3.5 w-3.5', out ? 'text-out' : 'text-flag')} />
      {status === 'NA' ? 'Inactive' : status}
    </span>
  );
}

/**
 * Axis domain: 0 (or the lowest range, rounded down to 5, when a range goes
 * negative: PPR points can) to the widest range rounded up to 5, at least 20.
 */
export function scaleDomain(predictions) {
  const lowest = Math.min(0, ...predictions.map((p) => p.confidenceLow));
  const widest = Math.max(20, ...predictions.map((p) => p.confidenceHigh));
  return { min: Math.floor(lowest / 5) * 5, max: Math.ceil(widest / 5) * 5 };
}

/** Multiples of `step` within [min, max]. */
function stepsBetween(min, max, step) {
  const values = [];
  for (let value = Math.ceil(min / step) * step; value <= max; value += step) values.push(value);
  return values;
}

function rowDescription(p) {
  const parts = [
    `${p.playerName}: ${p.predictedPoints.toFixed(1)} projected PPR points`,
    `80% range ${p.confidenceLow.toFixed(1)} to ${p.confidenceHigh.toFixed(1)}`,
  ];
  const matchup = matchupLabel(p.context);
  if (matchup) parts.push(matchup.replace('@', 'at'));
  const source = SOURCE_LABELS[p.features?.projection_source];
  if (source) parts.push(source);
  return parts.join(', ');
}

function YardLines({ min, max }) {
  return stepsBetween(min, max, 5).map((value) => (
    <span
      key={value}
      aria-hidden="true"
      className="absolute inset-y-0 w-px bg-yardline"
      style={{ left: `${((value - min) / (max - min)) * 100}%` }}
    />
  ));
}

function PlayerLine({ p, showInjury }) {
  const matchup = matchupLabel(p.context);
  const kickoff = kickoffLabel(p.context);
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="truncate font-condensed text-lg font-semibold leading-tight text-chalk">
          {p.playerName}
        </span>
        {showInjury && <InjuryChip status={p.context?.injury_status} />}
      </div>
      <div className="flex flex-wrap gap-x-3 text-sm text-chalk-secondary">
        {p.context?.team && <span>{p.context.team}</span>}
        {matchup && <span>{matchup}</span>}
        {kickoff && <span>{kickoff}</span>}
      </div>
    </div>
  );
}

/**
 * Each player's calibrated 80% range as a band on a shared points scale
 * marked like yard lines, with the projection as a marker. Overlapping bands
 * make a close call visible.
 */
export function RangeField({ predictions, showInjuries = false, animationKey }) {
  const [active, setActive] = useState(null);
  const [asTable, setAsTable] = useState(false);
  const { min, max } = scaleDomain(predictions);
  const pct = (value) => `${Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))}%`;
  const ticks = stepsBetween(min, max, 10);

  return (
    <section aria-labelledby="range-field-title" className="@container">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h3 id="range-field-title" className="text-sm text-chalk-secondary">
          Projected PPR points, with the range they land in 8 times out of 10
        </h3>
        <button
          type="button"
          onClick={() => setAsTable((v) => !v)}
          className="hit-area shrink-0 text-sm text-chalk underline decoration-yardline underline-offset-4 hover:decoration-chalk"
        >
          {asTable ? 'Show as chart' : 'Show as table'}
        </button>
      </div>

      {asTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-chalk-secondary">
              <tr className="border-b border-yardline">
                <th scope="col" className="py-2 pr-4 font-medium">Player</th>
                <th scope="col" className="py-2 pr-4 font-medium">Game</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">Projection</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">80% range</th>
                <th scope="col" className="py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {predictions.map((p) => (
                <tr key={p.playerId} className="border-b border-yardline/60">
                  <th scope="row" className="py-2 pr-4 font-medium text-chalk">
                    {p.playerName}
                    {showInjuries && <span className="ml-2"><InjuryChip status={p.context?.injury_status} /></span>}
                  </th>
                  <td className="py-2 pr-4 text-chalk-secondary">
                    {[p.context?.team, matchupLabel(p.context), kickoffLabel(p.context)].filter(Boolean).join(' ')}
                  </td>
                  <td className="py-2 pr-4 text-right text-chalk">{p.predictedPoints.toFixed(1)}</td>
                  <td className="py-2 pr-4 text-right text-chalk-secondary">
                    {p.confidenceLow.toFixed(1)} to {p.confidenceHigh.toFixed(1)}
                  </td>
                  <td className="py-2 text-chalk-secondary">
                    {SOURCE_LABELS[p.features?.projection_source] ?? 'Unknown'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div key={animationKey}>
          {/* Yard markers */}
          {/* Same columns and padding as the rows below, so markers align with bands */}
          <div aria-hidden="true" className="grid grid-cols-[1fr_3.5rem] gap-x-4 px-2 @lg:grid-cols-[minmax(9rem,13rem)_1fr_3.5rem]">
            <span className="hidden @lg:block" />
            <div className="relative h-6 font-condensed text-sm font-semibold text-chalk-muted">
              {ticks.map((value) => (
                <span
                  key={value}
                  className="absolute -translate-x-1/2 tabular-nums"
                  style={{ left: pct(value) }}
                >
                  {value}
                </span>
              ))}
            </div>
            <span className="hidden @lg:block" />
          </div>

          <ol className="space-y-1">
            {predictions.map((p) => {
              const isActive = active === p.playerId;
              return (
                <li
                  key={p.playerId}
                  tabIndex={0}
                  aria-label={rowDescription(p)}
                  // Hover is mouse-only: on touch, enter and leave both fire around a tap
                  onPointerEnter={(e) => e.pointerType === 'mouse' && setActive(p.playerId)}
                  onPointerLeave={(e) => e.pointerType === 'mouse' && setActive(null)}
                  onClick={() => setActive(p.playerId)}
                  onFocus={() => setActive(p.playerId)}
                  onBlur={() => setActive(null)}
                  className={cn(
                    'grid grid-cols-[1fr_3.5rem] gap-x-4 gap-y-2 rounded-md px-2 py-3 @lg:grid-cols-[minmax(9rem,13rem)_1fr_3.5rem] @lg:items-center',
                    isActive && 'bg-sideline/70'
                  )}
                >
                  <div className="col-span-2 @lg:col-span-1">
                    <PlayerLine p={p} showInjury={showInjuries} />
                  </div>

                  {/* The range on the field */}
                  <div aria-hidden="true" className="relative h-8">
                    <YardLines min={min} max={max} />
                    <span
                      className="range-in absolute top-1/2 h-2.5 -translate-y-1/2 rounded-[4px] bg-scrimmage/35"
                      style={{ left: pct(p.confidenceLow), width: `calc(${pct(p.confidenceHigh)} - ${pct(p.confidenceLow)})` }}
                    />
                    <span
                      className="marker-in absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-scrimmage shadow-[0_0_0_2px_var(--color-turf)]"
                      style={{ left: pct(p.predictedPoints) }}
                    />
                    {isActive && (
                      <div
                        role="presentation"
                        className="pointer-events-none absolute bottom-full z-10 mb-2 w-max -translate-x-1/2 rounded-md border border-yardline bg-turf px-3 py-2 text-left shadow-lg"
                        style={{ left: `clamp(5rem, ${pct(p.predictedPoints)}, calc(100% - 5rem))` }}
                      >
                        <div className="font-condensed text-lg font-semibold text-chalk">
                          {p.predictedPoints.toFixed(1)} pts
                        </div>
                        <div className="text-xs text-chalk-secondary">
                          80% range {p.confidenceLow.toFixed(1)} to {p.confidenceHigh.toFixed(1)}
                        </div>
                        {SOURCE_LABELS[p.features?.projection_source] && (
                          <div className="text-xs text-chalk-secondary">
                            {SOURCE_LABELS[p.features.projection_source]}
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  <div aria-hidden="true" className="text-right font-condensed text-2xl font-semibold tabular-nums text-chalk">
                    {p.predictedPoints.toFixed(1)}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
