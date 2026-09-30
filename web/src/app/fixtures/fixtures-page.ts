import { DatePipe } from '@angular/common';
import { httpResource } from '@angular/common/http';
import { Component, computed, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { api, Fixture, Team } from '../api';

export interface FixtureDay {
  date: string;
  fixtures: Fixture[];
}

/** Group fixtures (already sorted by kickoff) by local calendar day. */
export function groupByDay(fixtures: Fixture[]): FixtureDay[] {
  const days: FixtureDay[] = [];
  for (const fixture of fixtures) {
    const kickoff = new Date(fixture.kickoff_at);
    const date = [
      kickoff.getFullYear(),
      String(kickoff.getMonth() + 1).padStart(2, '0'),
      String(kickoff.getDate()).padStart(2, '0'),
    ].join('-');
    const last = days.at(-1);
    if (last?.date === date) {
      last.fixtures.push(fixture);
    } else {
      days.push({ date, fixtures: [fixture] });
    }
  }
  return days;
}

@Component({
  selector: 'app-fixtures-page',
  host: { class: 'page' },
  imports: [RouterLink, DatePipe],
  templateUrl: './fixtures-page.html',
})
export class FixturesPage {
  private readonly router = inject(Router);

  readonly competition = input.required<string>();

  protected readonly dayOptions = [7, 14, 30];
  protected readonly days = signal(14);

  protected readonly fixtures = httpResource<Fixture[]>(() => ({
    url: api.fixtures(this.competition()),
    params: { days: this.days() },
  }));
  protected readonly teams = httpResource<Team[]>(() => api.teams(this.competition()));

  protected readonly fixtureDays = computed(() => groupByDay(this.fixtures.value() ?? []));

  protected readonly home = signal('');
  protected readonly away = signal('');
  protected readonly canCompare = computed(
    () => this.home() !== '' && this.away() !== '' && this.home() !== this.away(),
  );

  protected compare(): void {
    if (!this.canCompare()) {
      return;
    }
    void this.router.navigate(['/', this.competition(), 'compare'], {
      queryParams: { home: this.home(), away: this.away() },
    });
  }
}
