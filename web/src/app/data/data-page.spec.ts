import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { SyncStatus } from '../api';
import { DataPage, seasonLabel, seasonOptions } from './data-page';

const league = (code: string, name: string, overrides = {}) => ({
  league: code,
  code: code.toUpperCase(),
  name,
  has_data: true,
  latest_result_at: '2026-10-19T19:00:00Z',
  last_checked_at: '2026-10-20T08:00:00Z',
  last_check_failed: false,
  queued: false,
  ...overrides,
});

const STATUS: SyncStatus = {
  current_season: 2026,
  first_season: 2014,
  workers_online: 1,
  queue: { todo: 3, doing: 1, failed: 0 },
  match_details_queued: 4,
  leagues: [
    league('EPL', 'Premier League'),
    league('La_liga', 'La Liga', { queued: true }),
    league('Serie_A', 'Serie A', {
      has_data: false,
      latest_result_at: null,
      last_checked_at: null,
    }),
  ],
};

/** Let the post's promise settle; the page then reloads the status. */
const tick = () => new Promise((resolve) => setTimeout(resolve));

describe('season helpers', () => {
  it('lists seasons newest first with labels', () => {
    expect(seasonOptions(2023, 2026)).toEqual([2026, 2025, 2024, 2023]);
    expect(seasonLabel(2026)).toBe('2026/27');
    expect(seasonLabel(2099)).toBe('2099/00');
  });
});

describe('DataPage', () => {
  let http: HttpTestingController;

  async function render(status: SyncStatus = STATUS) {
    TestBed.configureTestingModule({
      imports: [DataPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    const page = TestBed.createComponent(DataPage);
    page.detectChanges();
    http = TestBed.inject(HttpTestingController);
    http.expectOne('/api/sync').flush(status);
    await page.whenStable();
    return page;
  }

  afterEach(() => TestBed.resetTestingModule());

  it('shows worker, queue and league status', async () => {
    const page = await render();
    const text: string = page.nativeElement.textContent;

    expect(text).toContain('Worker running');
    expect(text).toContain('4 jobs to go');
    expect(text).toContain('4 player and shot details');
    const rows = [...page.nativeElement.querySelectorAll('.data-table tbody tr')].map(
      (r: Element) => r.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(rows[0]).toContain('Premier League');
    expect(rows[0]).toContain('Refresh');
    expect(rows[1]).toContain('queued…');
    expect(rows[2]).toContain('no data');
    expect(rows[2]).toContain('never');
  });

  it('warns when no worker is running', async () => {
    const page = await render({ ...STATUS, workers_online: 0 });
    expect(page.nativeElement.textContent).toContain('No worker running');
  });

  it('refreshes one league and reports what was queued', async () => {
    const page = await render();
    const button = page.nativeElement.querySelector(
      '.data-table tbody tr .action button',
    ) as HTMLButtonElement;
    button.click();

    const post = http.expectOne('/api/sync/refresh');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ leagues: ['EPL'] });
    post.flush({ queued: 1 });
    await tick();
    http.expectOne('/api/sync').flush(STATUS);
    await page.whenStable();

    expect(page.nativeElement.textContent).toContain('Queued 1 refresh.');
  });

  it('refreshes all leagues', async () => {
    const page = await render();
    (page.nativeElement.querySelector('.section-head button') as HTMLButtonElement).click();

    const post = http.expectOne('/api/sync/refresh');
    expect(post.request.body).toEqual({});
    post.flush({ queued: 0 });
    await tick();
    http.expectOne('/api/sync').flush(STATUS);
    await page.whenStable();

    expect(page.nativeElement.textContent).toContain('Already queued');
  });

  it('loads history from the chosen season for the chosen leagues', async () => {
    const page = await render();
    const select = page.nativeElement.querySelector('.history select') as HTMLSelectElement;
    expect(select.value).toBe('2021');
    select.value = '2019';
    select.dispatchEvent(new Event('change'));
    const boxes = page.nativeElement.querySelectorAll(
      '.history input[type=checkbox]',
    ) as NodeListOf<HTMLInputElement>;
    boxes[2].click();
    await page.whenStable();
    (page.nativeElement.querySelector('.history button') as HTMLButtonElement).click();

    const post = http.expectOne('/api/sync/history');
    expect(post.request.body).toEqual({ leagues: ['EPL', 'La_liga'], from_season: 2019 });
    post.flush({ queued: 16 });
    await tick();
    http.expectOne('/api/sync').flush(STATUS);
    await page.whenStable();

    expect(page.nativeElement.textContent).toContain('Queued 16 seasons.');
  });
});
