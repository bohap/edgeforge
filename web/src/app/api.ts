/** Shapes returned by the Python API (see src/edgeforge/api/schemas.py). */

export interface Competition {
  code: string;
  name: string;
  country: string | null;
}

export interface Team {
  id: string;
  name: string;
}

export interface Fixture {
  match_id: string;
  kickoff_at: string;
  home: Team;
  away: Team;
}

/** Summary over a run of matches. xG averages are null when no match had xG. */
export interface Form {
  matches: number;
  results: string;
  wins: number;
  draws: number;
  losses: number;
  points_per_game: number;
  goals_for: number;
  goals_against: number;
  xg_for: number | null;
  xg_against: number | null;
  xg_matches: number;
  both_scored: number;
  over_2_5: number;
}

export interface FormWindow {
  last: number;
  overall: Form | null;
  at_venue: Form | null;
}

export interface TeamMatch {
  kickoff_at: string;
  opponent: Team;
  venue: 'home' | 'away';
  goals_for: number;
  goals_against: number;
  xg_for: number | null;
  xg_against: number | null;
  result: 'W' | 'D' | 'L';
}

export interface Meeting {
  kickoff_at: string;
  home: Team;
  away: Team;
  home_goals: number;
  away_goals: number;
  home_xg: number | null;
  away_xg: number | null;
}

export interface Estimate {
  expected_home_goals: number;
  expected_away_goals: number;
  home_win: number;
  draw: number;
  away_win: number;
  both_score: number;
  over_2_5: number;
  likely_score: [number, number];
  likely_score_probability: number;
}

export interface TeamSide {
  team: Team;
  last_played: string | null;
  form: FormWindow[];
  recent: TeamMatch[];
}

export interface Comparison {
  as_of: string;
  competition: Competition;
  home: TeamSide;
  away: TeamSide;
  head_to_head: Meeting[];
  estimate: Estimate | null;
}

export const api = {
  competitions: () => '/api/competitions',
  fixtures: (code: string) => `/api/competitions/${encodeURIComponent(code)}/fixtures`,
  teams: (code: string) => `/api/competitions/${encodeURIComponent(code)}/teams`,
  compare: (code: string) => `/api/competitions/${encodeURIComponent(code)}/compare`,
};

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function decimal(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? '–' : value.toFixed(digits);
}
