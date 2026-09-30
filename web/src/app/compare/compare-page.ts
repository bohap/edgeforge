import { DatePipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, computed, input, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { api, Comparison, decimal, Form, percent } from '../api';

export const WINDOWS = [5, 10, 20];

type Better = 'higher' | 'lower' | null;

export interface Metric {
  label: string;
  value: (form: Form) => number | null;
  format: (form: Form) => string;
  better: Better;
}

export const METRICS: Metric[] = [
  {
    label: 'Points per game',
    value: (f) => f.points_per_game,
    format: (f) => decimal(f.points_per_game),
    better: 'higher',
  },
  {
    label: 'Goals for',
    value: (f) => f.goals_for,
    format: (f) => decimal(f.goals_for),
    better: 'higher',
  },
  {
    label: 'Goals against',
    value: (f) => f.goals_against,
    format: (f) => decimal(f.goals_against),
    better: 'lower',
  },
  {
    label: 'xG for',
    value: (f) => f.xg_for,
    format: (f) => decimal(f.xg_for) + xgNote(f),
    better: 'higher',
  },
  {
    label: 'xG against',
    value: (f) => f.xg_against,
    format: (f) => decimal(f.xg_against) + xgNote(f),
    better: 'lower',
  },
  {
    label: 'Both teams scored',
    value: (f) => f.both_scored / f.matches,
    format: (f) => `${f.both_scored} of ${f.matches}`,
    better: null,
  },
  {
    label: 'Over 2.5 goals',
    value: (f) => f.over_2_5 / f.matches,
    format: (f) => `${f.over_2_5} of ${f.matches}`,
    better: null,
  },
];

function xgNote(form: Form): string {
  return form.xg_for !== null && form.xg_matches < form.matches ? ` (${form.xg_matches} m)` : '';
}

/** Which side has the better value: 'home', 'away' or null (tie, unknown, or no direction). */
export function betterSide(
  metric: Metric,
  home: Form | null,
  away: Form | null,
): 'home' | 'away' | null {
  if (!metric.better || !home || !away) {
    return null;
  }
  const h = metric.value(home);
  const a = metric.value(away);
  if (h === null || a === null || h === a) {
    return null;
  }
  const homeHigher = h > a;
  return homeHigher === (metric.better === 'higher') ? 'home' : 'away';
}

@Component({
  selector: 'app-compare-page',
  host: { class: 'page' },
  imports: [DatePipe, RouterLink],
  templateUrl: './compare-page.html',
})
export class ComparePage {
  readonly competition = input.required<string>();
  readonly home = input.required<string>();
  readonly away = input.required<string>();
  readonly kickoff = input<string>();

  protected readonly windows = WINDOWS;
  protected readonly metrics = METRICS;
  protected readonly percent = percent;
  protected readonly decimal = decimal;

  protected readonly window = signal(WINDOWS[0]);
  protected readonly venueOnly = signal(false);

  protected readonly comparison = httpResource<Comparison>(() =>
    this.home() && this.away()
      ? {
          url: api.compare(this.competition()),
          params: { home: this.home(), away: this.away(), last: WINDOWS },
        }
      : undefined,
  );

  protected readonly forms = computed(() => {
    const c = this.comparison.value();
    if (!c) {
      return null;
    }
    const pick = (side: Comparison['home']) => {
      const w = side.form.find((f) => f.last === this.window());
      return (this.venueOnly() ? w?.at_venue : w?.overall) ?? null;
    };
    return { home: pick(c.home), away: pick(c.away) };
  });

  protected readonly recentShown = 10;

  protected better(metric: Metric, side: 'home' | 'away'): boolean {
    const forms = this.forms();
    return !!forms && betterSide(metric, forms.home, forms.away) === side;
  }
}
