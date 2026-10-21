import { DatePipe } from '@angular/common';
import { Component, computed, input, signal } from '@angular/core';

import { decimal, MarketSide, percent, Polymarket } from '../api';

/** Odds ranges worth a look when the model sees an edge. */
export const VALUE_ODDS = 1.7;
export const MAYBE_ODDS = 1.5;

export type Tier = 'value' | 'maybe' | null;

export function tier(side: MarketSide): Tier {
  if (side.edge <= 0) {
    return null;
  }
  if (side.odds >= VALUE_ODDS) {
    return 'value';
  }
  return side.odds >= MAYBE_ODDS ? 'maybe' : null;
}

export const GROUPS: { code: MarketSide['market_code']; title: string }[] = [
  { code: 'MATCH_RESULT', title: 'Result' },
  { code: 'WIN_MARGIN', title: 'Spread' },
  { code: 'TOTAL_GOALS', title: 'Total goals' },
  { code: 'BTTS', title: 'Both teams to score' },
  { code: 'TEAM_TOTAL', title: 'Team goals' },
];

/** Human label for a side, e.g. "Forest −1.5 (win by 2+)" or "Under 2.5". */
export function sideLabel(side: MarketSide, home: string, away: string): string {
  const team = (s?: 'home' | 'away') => (s === 'away' ? away : home);
  const other = (s?: 'home' | 'away') => (s === 'away' ? home : away);
  const { line, min_margin } = side.params;
  switch (side.market_code) {
    case 'MATCH_RESULT': {
      const names: Record<string, [string, string]> = {
        HOME: [`${home} win`, `${away} or draw`],
        DRAW: ['Draw', 'No draw'],
        AWAY: [`${away} win`, `${home} or draw`],
      };
      return names[side.outcome][side.negated ? 1 : 0];
    }
    case 'WIN_MARGIN': {
      const handicap = (min_margin ?? 1) - 0.5;
      return side.negated
        ? `${other(side.params.side)} +${handicap} (not lose by ${min_margin}+)`
        : `${team(side.params.side)} −${handicap} (win by ${min_margin}+)`;
    }
    case 'TOTAL_GOALS':
      return `${side.negated ? 'Under' : 'Over'} ${line} goals`;
    case 'BTTS':
      return side.negated ? 'Not both teams score' : 'Both teams score';
    case 'TEAM_TOTAL':
      return `${team(side.params.side)} ${side.negated ? 'under' : 'over'} ${line} goals`;
  }
}

/** Sort key inside a group: by team, then line or margin, then the quoted side first. */
function order(side: MarketSide): string {
  const outcome = ['HOME', 'DRAW', 'AWAY'].indexOf(side.outcome);
  const team = side.params.side === 'away' ? 1 : 0;
  const size = (side.params.line ?? side.params.min_margin ?? 0).toFixed(1).padStart(5, '0');
  return `${team}|${size}|${side.negated ? 1 : 0}|${outcome}`;
}

export type Filter = 'interesting' | 'edge' | 'all';

@Component({
  selector: 'app-markets',
  imports: [DatePipe],
  templateUrl: './markets.html',
})
export class Markets {
  readonly polymarket = input.required<Polymarket>();
  readonly home = input.required<string>();
  readonly away = input.required<string>();

  protected readonly percent = percent;
  protected readonly decimal = decimal;
  protected readonly tier = tier;
  protected readonly VALUE_ODDS = VALUE_ODDS;
  protected readonly MAYBE_ODDS = MAYBE_ODDS;

  protected readonly filter = signal<Filter>('interesting');

  protected readonly groups = computed(() => {
    const shown = this.polymarket().sides.filter((s) => {
      switch (this.filter()) {
        case 'interesting':
          return s.odds >= MAYBE_ODDS;
        case 'edge':
          return tier(s) !== null;
        case 'all':
          return true;
      }
    });
    return GROUPS.map((g) => ({
      ...g,
      sides: shown
        .filter((s) => s.market_code === g.code)
        .sort((a, b) => order(a).localeCompare(order(b))),
    })).filter((g) => g.sides.length > 0);
  });

  protected label(side: MarketSide): string {
    return sideLabel(side, this.home(), this.away());
  }
}
