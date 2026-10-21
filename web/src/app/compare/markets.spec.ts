import { TestBed } from '@angular/core/testing';

import { MarketSide, Polymarket } from '../api';
import { Markets, sideLabel, tier } from './markets';

function side(overrides: Partial<MarketSide>): MarketSide {
  return {
    market_code: 'TOTAL_GOALS',
    params: { line: 2.5 },
    outcome: 'OVER',
    negated: false,
    price: 0.55,
    odds: 1.78,
    market_probability: 0.545,
    model_probability: 0.63,
    edge: 0.12,
    liquidity: 1000,
    url: 'https://polymarket.com/event/epl-ips-not-2026-10-23-more-markets',
    ...overrides,
  };
}

describe('tier', () => {
  it('tags positive edges by odds range', () => {
    expect(tier(side({ odds: 1.78, edge: 0.12 }))).toBe('value');
    expect(tier(side({ odds: 1.7, edge: 0.01 }))).toBe('value');
    expect(tier(side({ odds: 1.63, edge: 0.04 }))).toBe('maybe');
    expect(tier(side({ odds: 1.5, edge: 0.04 }))).toBe('maybe');
    expect(tier(side({ odds: 1.4, edge: 0.1 }))).toBeNull();
    expect(tier(side({ odds: 2.5, edge: -0.05 }))).toBeNull();
    expect(tier(side({ odds: 2.5, edge: 0 }))).toBeNull();
  });
});

describe('sideLabel', () => {
  const label = (s: Partial<MarketSide>) => sideLabel(side(s), 'Ipswich', 'Forest');

  it('names result sides and their complements', () => {
    expect(label({ market_code: 'MATCH_RESULT', params: {}, outcome: 'HOME' })).toBe('Ipswich win');
    expect(label({ market_code: 'MATCH_RESULT', params: {}, outcome: 'HOME', negated: true })).toBe(
      'Forest or draw',
    );
    expect(label({ market_code: 'MATCH_RESULT', params: {}, outcome: 'DRAW', negated: true })).toBe(
      'No draw',
    );
    expect(label({ market_code: 'MATCH_RESULT', params: {}, outcome: 'AWAY', negated: true })).toBe(
      'Ipswich or draw',
    );
  });

  it('names spreads as handicaps', () => {
    const spread = {
      market_code: 'WIN_MARGIN' as const,
      params: { side: 'away' as const, min_margin: 2 },
      outcome: 'YES',
    };
    expect(label(spread)).toBe('Forest −1.5 (win by 2+)');
    expect(label({ ...spread, negated: true })).toBe('Ipswich +1.5 (not lose by 2+)');
  });

  it('names totals, both teams to score and team goals', () => {
    expect(label({})).toBe('Over 2.5 goals');
    expect(label({ negated: true })).toBe('Under 2.5 goals');
    expect(label({ market_code: 'BTTS', params: {}, outcome: 'YES' })).toBe('Both teams score');
    expect(label({ market_code: 'BTTS', params: {}, outcome: 'YES', negated: true })).toBe(
      'Not both teams score',
    );
    expect(
      label({
        market_code: 'TEAM_TOTAL',
        params: { side: 'home', line: 1.5 },
        outcome: 'OVER',
        negated: true,
      }),
    ).toBe('Ipswich under 1.5 goals');
  });
});

describe('Markets', () => {
  const POLYMARKET: Polymarket = {
    url: 'https://polymarket.com/event/epl-ips-not-2026-10-23',
    observed_at: '2026-10-21T06:09:00Z',
    sides: [
      side({}),
      side({ negated: true, odds: 2.12, edge: -0.21, model_probability: 0.37 }),
      side({ params: { line: 0.5 }, odds: 1.06, edge: -0.01, model_probability: 0.93 }),
      side({
        market_code: 'MATCH_RESULT',
        params: {},
        outcome: 'HOME',
        odds: 3.12,
        edge: -0.02,
        url: 'https://polymarket.com/event/epl-ips-not-2026-10-23',
      }),
      side({ market_code: 'BTTS', params: {}, outcome: 'YES', odds: 1.63, edge: 0.04 }),
    ],
  };

  async function render() {
    const fixture = TestBed.createComponent(Markets);
    fixture.componentRef.setInput('polymarket', POLYMARKET);
    fixture.componentRef.setInput('home', 'Ipswich');
    fixture.componentRef.setInput('away', 'Forest');
    await fixture.whenStable();
    return fixture;
  }

  const rows = (el: HTMLElement) =>
    [...el.querySelectorAll('.market-table tbody tr:not(.group)')].map(
      (r) => r.querySelector('th')?.textContent?.replace(/\s+/g, ' ').trim() ?? '',
    );

  it('shows odds 1.5+ by default, grouped, with tags and links', async () => {
    const fixture = await render();
    const el: HTMLElement = fixture.nativeElement;

    expect(rows(el)).toEqual([
      'Ipswich win',
      'Over 2.5 goals value',
      'Under 2.5 goals',
      'Both teams score 1.5–1.7',
    ]);
    const groups = [...el.querySelectorAll('tr.group')].map((g) => g.textContent?.trim());
    expect(groups).toEqual(['Result', 'Total goals', 'Both teams to score']);
    expect(el.querySelector('a.external')?.getAttribute('href')).toBe(POLYMARKET.url);
    const links = [...el.querySelectorAll('td.link a')].map((a) => a.getAttribute('href'));
    expect(links[0]).toBe('https://polymarket.com/event/epl-ips-not-2026-10-23');
    expect(links.every((href) => href?.startsWith('https://polymarket.com/event/'))).toBe(true);
    expect(el.querySelector('td.link a')?.getAttribute('target')).toBe('_blank');
  });

  it('filters to model edge or shows everything', async () => {
    const fixture = await render();
    const el: HTMLElement = fixture.nativeElement;
    const button = (name: string) =>
      [...el.querySelectorAll('.segmented button')].find(
        (b) => b.textContent?.trim() === name,
      ) as HTMLButtonElement;

    button('Model edge').click();
    await fixture.whenStable();
    expect(rows(el)).toEqual(['Over 2.5 goals value', 'Both teams score 1.5–1.7']);

    button('All').click();
    await fixture.whenStable();
    expect(rows(el)).toHaveLength(5);
    expect(rows(el)).toContain('Over 0.5 goals');
  });
});
