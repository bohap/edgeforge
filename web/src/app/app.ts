import { httpResource } from '@angular/common/http';
import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { api, Competition } from './api';
import { DataVersion } from './data-version';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  template: `
    <header class="topbar">
      <a class="brand" routerLink="/">EdgeForge</a>
      <nav class="leagues" aria-label="Competitions">
        @for (c of competitions.hasValue() ? competitions.value() : []; track c.code) {
          <a
            [routerLink]="['/', c.code]"
            [class.active]="c.code === currentCompetition()"
            [attr.aria-current]="c.code === currentCompetition() ? 'page' : null"
            >{{ c.name }}</a
          >
        }
      </nav>
      <a
        class="data-link"
        routerLink="/data"
        [class.active]="currentCompetition() === 'data'"
        [attr.aria-current]="currentCompetition() === 'data' ? 'page' : null"
        >Data</a
      >
    </header>
    <main>
      <router-outlet />
    </main>
    <footer class="footer">
      Statistical estimates for fun and research, not certainties. Please bet responsibly.
    </footer>
  `,
})
export class App {
  private readonly router = inject(Router);

  private readonly dataVersion = inject(DataVersion);

  protected readonly competitions = httpResource<Competition[]>(() => {
    this.dataVersion.value();
    return api.competitions();
  });

  private readonly url = toSignal(
    this.router.events.pipe(
      filter((e) => e instanceof NavigationEnd),
      map((e) => e.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  protected readonly currentCompetition = computed(
    () => this.url().split(/[/?#]/).filter(Boolean)[0] ?? '',
  );
}
