import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { Fixture } from '../api';
import { FixturesPage, groupByDay } from './fixtures-page';

function fixture(id: string, kickoff: Date, home: string, away: string): Fixture {
  return {
    match_id: id,
    kickoff_at: kickoff.toISOString(),
    home: { id: `${id}-h`, name: home },
    away: { id: `${id}-a`, name: away },
  };
}

describe('groupByDay', () => {
  it('groups consecutive fixtures by local date', () => {
    const days = groupByDay([
      fixture('1', new Date(2026, 9, 10, 12, 30), 'Arsenal', 'Leeds'),
      fixture('2', new Date(2026, 9, 10, 15, 0), 'Chelsea', 'Fulham'),
      fixture('3', new Date(2026, 9, 11, 14, 0), 'Everton', 'Hull'),
    ]);

    expect(days.map((d) => [d.date, d.fixtures.length])).toEqual([
      ['2026-10-10', 2],
      ['2026-10-11', 1],
    ]);
  });

  it('returns nothing for no fixtures', () => {
    expect(groupByDay([])).toEqual([]);
  });
});

describe('FixturesPage', () => {
  it('shows fixtures linking to the comparison', async () => {
    TestBed.configureTestingModule({
      imports: [FixturesPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    const page = TestBed.createComponent(FixturesPage);
    page.componentRef.setInput('competition', 'EPL');
    page.detectChanges();

    const http = TestBed.inject(HttpTestingController);
    http
      .expectOne((r) => r.url === '/api/competitions/EPL/fixtures' && r.params.get('days') === '14')
      .flush([fixture('m1', new Date(2026, 9, 10, 12, 30), 'Arsenal', 'Leeds')]);
    http.expectOne('/api/competitions/EPL/teams').flush([
      { id: 't1', name: 'Arsenal' },
      { id: 't2', name: 'Leeds' },
    ]);
    await page.whenStable();

    const link: HTMLAnchorElement = page.nativeElement.querySelector('a.fixture');
    expect(link.textContent).toContain('Arsenal');
    expect(link.textContent).toContain('Leeds');
    expect(link.getAttribute('href')).toContain('/EPL/compare?home=m1-h&away=m1-a');
    expect(page.nativeElement.querySelectorAll('option').length).toBe(6);
  });

  it('says when there are no fixtures', async () => {
    TestBed.configureTestingModule({
      imports: [FixturesPage],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    const page = TestBed.createComponent(FixturesPage);
    page.componentRef.setInput('competition', 'EPL');
    page.detectChanges();

    const http = TestBed.inject(HttpTestingController);
    http.expectOne((r) => r.url === '/api/competitions/EPL/fixtures').flush([]);
    http.expectOne('/api/competitions/EPL/teams').flush([]);
    await page.whenStable();

    expect(page.nativeElement.textContent).toContain('No fixtures in the next 14 days');
  });
});
