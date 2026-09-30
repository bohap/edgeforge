import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { Comparison, Form } from '../api';
import { betterSide, ComparePage, METRICS } from './compare-page';

function form(overrides: Partial<Form> = {}): Form {
  return {
    matches: 5,
    results: 'WWDLW',
    wins: 3,
    draws: 1,
    losses: 1,
    points_per_game: 2,
    goals_for: 1.8,
    goals_against: 0.8,
    xg_for: 1.9,
    xg_against: 1.0,
    xg_matches: 5,
    both_scored: 2,
    over_2_5: 3,
    ...overrides,
  };
}

const metric = (label: string) => METRICS.find((m) => m.label === label)!;

describe('betterSide', () => {
  it('prefers the higher value when higher is better', () => {
    const m = metric('Points per game');
    expect(betterSide(m, form({ points_per_game: 2.4 }), form({ points_per_game: 1.2 }))).toBe(
      'home',
    );
    expect(betterSide(m, form({ points_per_game: 1 }), form({ points_per_game: 1.2 }))).toBe(
      'away',
    );
  });

  it('prefers the lower value when lower is better', () => {
    const m = metric('Goals against');
    expect(betterSide(m, form({ goals_against: 0.6 }), form({ goals_against: 1.4 }))).toBe('home');
  });

  it('has no winner for ties, missing xG or neutral rows', () => {
    expect(betterSide(metric('Goals for'), form(), form())).toBeNull();
    expect(betterSide(metric('xG for'), form({ xg_for: null }), form())).toBeNull();
    expect(betterSide(metric('Over 2.5 goals'), form({ over_2_5: 5 }), form())).toBeNull();
    expect(betterSide(metric('Goals for'), null, form())).toBeNull();
  });

  it('marks xG averages that cover only some matches', () => {
    expect(metric('xG for').format(form({ xg_matches: 3 }))).toBe('1.90 (3 m)');
    expect(metric('xG for').format(form({ xg_for: null, xg_matches: 0 }))).toBe('–');
  });
});

const team = (id: string, name: string) => ({ id, name });

const COMPARISON: Comparison = {
  as_of: '2026-10-01T00:00:00Z',
  competition: { code: 'EPL', name: 'Premier League', country: 'England' },
  home: {
    team: team('h', 'Arsenal'),
    last_played: '2026-09-19T14:00:00Z',
    form: [
      { last: 5, overall: form({ results: 'LWWWW', points_per_game: 2.4 }), at_venue: form() },
      { last: 10, overall: form({ matches: 10 }), at_venue: null },
      { last: 20, overall: null, at_venue: null },
    ],
    recent: [
      {
        kickoff_at: '2026-09-19T14:00:00Z',
        opponent: team('b', 'Brighton'),
        venue: 'away',
        goals_for: 0,
        goals_against: 3,
        xg_for: 1.2,
        xg_against: 2.1,
        result: 'L',
      },
    ],
  },
  away: {
    team: team('a', 'Leeds'),
    last_played: null,
    form: [
      { last: 5, overall: form({ results: 'DWDDW', points_per_game: 1.8 }), at_venue: null },
      { last: 10, overall: null, at_venue: null },
      { last: 20, overall: null, at_venue: null },
    ],
    recent: [],
  },
  head_to_head: [
    {
      kickoff_at: '2026-01-31T15:00:00Z',
      home: team('a', 'Leeds'),
      away: team('h', 'Arsenal'),
      home_goals: 0,
      away_goals: 4,
      home_xg: 0.18,
      away_xg: 3.54,
    },
  ],
  estimate: {
    expected_home_goals: 1.83,
    expected_away_goals: 0.98,
    home_win: 0.564,
    draw: 0.247,
    away_win: 0.189,
    both_score: 0.53,
    over_2_5: 0.53,
    likely_score: [1, 1],
    likely_score_probability: 0.118,
  },
};

async function render(comparison: Comparison) {
  TestBed.configureTestingModule({
    imports: [ComparePage],
    providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
  });
  const page = TestBed.createComponent(ComparePage);
  page.componentRef.setInput('competition', 'EPL');
  page.componentRef.setInput('home', 'h');
  page.componentRef.setInput('away', 'a');
  page.detectChanges();
  const request = TestBed.inject(HttpTestingController).expectOne(
    (r) => r.url === '/api/competitions/EPL/compare',
  );
  expect(request.request.params.get('home')).toBe('h');
  expect(request.request.params.getAll('last')).toEqual(['5', '10', '20']);
  request.flush(comparison);
  await page.whenStable();
  return page;
}

describe('ComparePage', () => {
  it('shows the estimate, form, recent matches and head to head', async () => {
    const page = await render(COMPARISON);
    const text: string = page.nativeElement.textContent;

    expect(text).toContain('Arsenal');
    expect(text).toContain('Estimated probabilities');
    const segments = [...page.nativeElement.querySelectorAll('.seg')].map((s: Element) =>
      s.textContent?.trim(),
    );
    expect(segments).toEqual(['56%', '25%', '19%']);
    expect(text).toContain('1–1');
    expect(text).toContain('not a certainty');
    const chips = [...page.nativeElement.querySelectorAll('.compare-table .chip')].map(
      (c: Element) => c.textContent,
    );
    expect(chips.join('')).toBe('LWWWWDWDDW');
    expect(page.nativeElement.querySelector('td.better')?.textContent).toContain('2.40');
    expect(text).toContain('@ Brighton');
    expect(text).toContain('Leeds – Arsenal');
    expect(text).toContain('No matches in the data.');
    for (const banned of ['guaranteed', 'safe bet', 'lock', "can't lose", '100%']) {
      expect(text.toLowerCase()).not.toContain(banned);
    }
  });

  it('switches the form window and handles a missing estimate', async () => {
    const page = await render({ ...COMPARISON, estimate: null });

    expect(page.nativeElement.textContent).toContain('Not available');
    const tenButton = [...page.nativeElement.querySelectorAll('.segmented button')].find(
      (b: Element) => b.textContent?.trim() === 'Last 10',
    ) as HTMLButtonElement;
    tenButton.click();
    await page.whenStable();

    const cells = [...page.nativeElement.querySelectorAll('.compare-table tbody tr')].map(
      (r: Element) => r.textContent,
    );
    expect(cells.find((c) => c?.includes('Both teams scored'))).toContain('2 of 10');
  });
});
