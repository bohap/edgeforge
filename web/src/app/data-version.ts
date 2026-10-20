import { Injectable, signal } from '@angular/core';

/** Bumped whenever the data changes, so views that list it (the league tabs) reload. */
@Injectable({ providedIn: 'root' })
export class DataVersion {
  readonly value = signal(0);

  bump(): void {
    this.value.update((v) => v + 1);
  }
}
