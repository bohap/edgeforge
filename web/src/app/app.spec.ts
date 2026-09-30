import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';

describe('App', () => {
  it('lists competitions from the API in the header', async () => {
    TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();

    TestBed.inject(HttpTestingController)
      .expectOne('/api/competitions')
      .flush([
        { code: 'EPL', name: 'Premier League', country: 'England' },
        { code: 'SERIE_A', name: 'Serie A', country: 'Italy' },
      ]);
    await fixture.whenStable();

    const links = [...fixture.nativeElement.querySelectorAll('.leagues a')].map((a: Element) =>
      a.textContent?.trim(),
    );
    expect(links).toEqual(['Premier League', 'Serie A']);
    expect(fixture.nativeElement.textContent).toContain('not certainties');
  });
});
