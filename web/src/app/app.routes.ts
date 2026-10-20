import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'EPL' },
  {
    path: 'data',
    loadComponent: () => import('./data/data-page').then((m) => m.DataPage),
  },
  {
    path: ':competition/compare',
    loadComponent: () => import('./compare/compare-page').then((m) => m.ComparePage),
  },
  {
    path: ':competition',
    loadComponent: () => import('./fixtures/fixtures-page').then((m) => m.FixturesPage),
  },
];
