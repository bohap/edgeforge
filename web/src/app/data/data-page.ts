import { DatePipe } from '@angular/common';
import { HttpClient, httpResource } from '@angular/common/http';
import { Component, computed, DestroyRef, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Queued, SyncStatus, syncApi } from '../api';
import { DataVersion } from '../data-version';

export const POLL_MS = 5000;

/** Seasons offered for a history load, newest first. */
export function seasonOptions(first: number, current: number): number[] {
  const seasons = [];
  for (let s = current; s >= first; s--) {
    seasons.push(s);
  }
  return seasons;
}

export function seasonLabel(start: number): string {
  return `${start}/${String((start + 1) % 100).padStart(2, '0')}`;
}

@Component({
  selector: 'app-data-page',
  host: { class: 'page' },
  imports: [DatePipe],
  templateUrl: './data-page.html',
})
export class DataPage {
  private readonly http = inject(HttpClient);
  private readonly dataVersion = inject(DataVersion);

  protected readonly status = httpResource<SyncStatus>(() => syncApi.status());
  /** The latest status; reading an errored resource's value() throws. */
  protected readonly current = computed(() =>
    this.status.hasValue() ? this.status.value() : undefined,
  );
  protected readonly seasonLabel = seasonLabel;

  protected readonly busy = signal(false);
  protected readonly message = signal('');

  protected readonly fromSeason = signal<number | null>(null);
  protected readonly selected = signal<Set<string> | null>(null);

  protected readonly seasons = computed(() => {
    const s = this.current();
    return s ? seasonOptions(s.first_season, s.current_season) : [];
  });
  protected readonly chosenFromSeason = computed(
    () => this.fromSeason() ?? (this.current()?.current_season ?? 0) - 5,
  );
  protected readonly chosenLeagues = computed(
    () => this.selected() ?? new Set((this.current()?.leagues ?? []).map((l) => l.league)),
  );
  protected readonly working = computed(() => {
    const q = this.current()?.queue;
    return !!q && q.todo + q.doing > 0;
  });

  constructor() {
    const timer = setInterval(() => this.status.reload(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));

    // New leagues appear in the header as soon as their first data lands.
    let withData = -1;
    effect(() => {
      const count = this.current()?.leagues.filter((l) => l.has_data).length;
      if (count !== undefined && count !== withData) {
        if (withData !== -1) {
          this.dataVersion.bump();
        }
        withData = count;
      }
    });
  }

  protected toggleLeague(league: string, checked: boolean): void {
    const next = new Set(this.chosenLeagues());
    if (checked) {
      next.add(league);
    } else {
      next.delete(league);
    }
    this.selected.set(next);
  }

  protected refresh(leagues?: string[]): Promise<void> {
    return this.queue(syncApi.refresh(), leagues ? { leagues } : {}, 'refresh');
  }

  protected loadHistory(): Promise<void> {
    return this.queue(
      syncApi.history(),
      { leagues: [...this.chosenLeagues()], from_season: this.chosenFromSeason() },
      'season',
    );
  }

  private async queue(url: string, body: object, noun: string): Promise<void> {
    this.busy.set(true);
    this.message.set('');
    try {
      const { queued } = await firstValueFrom(this.http.post<Queued>(url, body));
      this.message.set(
        queued === 0
          ? 'Already queued, nothing new to add.'
          : `Queued ${queued} ${noun}${queued === 1 ? '' : 's'}.`,
      );
    } catch {
      this.message.set('Could not queue the request. Is edgeforge serve running?');
    } finally {
      this.busy.set(false);
      this.status.reload();
    }
  }
}
