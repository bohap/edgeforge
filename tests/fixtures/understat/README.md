# Understat fixtures

Real responses recorded on 2026-09-29, unmodified:

| File | Request |
|------|---------|
| `league_EPL_2025.json` | `GET /getLeagueData/EPL/2025` (completed 2025/26 season) |
| `league_EPL_2026.json` | `GET /getLeagueData/EPL/2026` (2026/27, mostly future fixtures) |
| `match_28778.json` | `GET /getMatchData/28778` (Liverpool 4–2 Bournemouth, 15 Aug 2025) |

Re-record with the XHR headers from `edgeforge.providers.understat.client.HEADERS`, e.g.

```bash
curl --compressed -H 'X-Requested-With: XMLHttpRequest' -H 'Referer: https://understat.com/' \
  -A 'Mozilla/5.0' https://understat.com/getMatchData/28778 > match_28778.json
```
