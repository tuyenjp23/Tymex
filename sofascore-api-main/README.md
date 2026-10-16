# @devneonix/sofascore-api

A TypeScript wrapper around the SofaScore API. Exposes a ready-to-use Express HTTP server and a programmatic `SofascoreRepository` for use in your own Node.js apps.

---

## Installation

```bash
npm install @devneonix/sofascore-api
```

---

## Usage

### As a library

```typescript
import { SofascoreRepository } from '@devneonix/sofascore-api';

// Get fixtures for a sport and date
const fixtures = await SofascoreRepository.getFixtures('football', '2026-03-29');

// Get complete match data in a single call
const fullData = await SofascoreRepository.getEventFullData('football', '15655701');
console.log(fullData.event);
console.log(fullData.statistics);
console.log(fullData.standings);
```

### As an HTTP server

The package ships with a built-in Express server. Run it directly:

```bash
PORT=3001 node dist/server.js
```

All endpoints are prefixed with `/api`.

---

## HTTP Endpoints

### Fixtures

#### `GET /api/:sport/fixtures/:date`

Returns all scheduled events for a given sport and date. Filtered to the **America/Lima (UTC-5)** timezone by default.

| Param | Type | Description |
|---|---|---|
| `sport` | path | `football`, `basket`, `tenis` |
| `date` | path | `YYYY-MM-DD` |
| `country` | query (optional) | ISO country code (e.g. `PE`). Omit for global. |

```bash
GET /api/football/fixtures/2026-03-29
GET /api/football/fixtures/2026-03-29?country=PE
```

```json
{
  "events": [
    {
      "id": 15655701,
      "homeTeam": { "name": "Team A" },
      "awayTeam": { "name": "Team B" },
      "startTimestamp": 1743274800,
      "odds": { ... }
    }
  ]
}
```

---

### Full Match Data

#### `GET /api/:sport/:eventId/full-data`

Returns **everything** about a match in a single request. Makes 8 parallel calls internally:

- Event info
- Odds
- Lineups
- Team streaks
- H2H history package (local, visita, entre ambos)
- Goal distributions
- Standings
- Statistics

```bash
GET /api/football/15655701/full-data
```

```json
{
  "event": { ... },
  "odds": { "markets": [ ... ] },
  "lineups": { "home": { ... }, "away": { ... }, "confirmed": true },
  "teamStreaks": { "general": [ ... ], "head2head": [ ... ] },
  "h2hHistory": {
    "home": { "last": [ ... ], "next": [ ... ] },
    "away": { "last": [ ... ], "next": [ ... ] },
    "between": [ ... ]
  },
  "goalDistributions": { "home": { ... }, "away": { ... } },
  "standings": { "standings": [ ... ] },
  "statistics": { "statistics": [ ... ] }
}
```

---

### Individual Event Endpoints

#### `GET /api/event/:eventId/lineups`

Returns starting lineup, substitutes and missing players for both teams.

```json
{
  "home": {
    "players": [ { "name": "...", "position": "G", "jerseyNumber": "1" } ],
    "substitutes": [ ... ],
    "missingPlayers": [ ... ],
    "formation": "4-3-3"
  },
  "away": { ... },
  "confirmed": true
}
```

---

#### `GET /api/event/:eventId/odds`

Returns all betting markets with decimal odds.

```json
{
  "markets": [
    {
      "id": 1,
      "name": "1X2",
      "isMain": true,
      "choices": [
        { "name": "1", "decimalValue": 2.10 },
        { "name": "X", "decimalValue": 3.40 },
        { "name": "2", "decimalValue": 3.20 }
      ]
    }
  ]
}
```

---

#### `GET /api/event/:eventId/details`

Returns odds + lineups combined.

```json
{
  "odds": { ... },
  "lineups": { ... }
}
```

---

#### `GET /api/event/:eventId/team-streaks`

Returns current streaks for home and away teams (wins, unbeaten runs, goals, cards, etc.).

```json
{
  "general": [
    { "name": "No losses", "value": "8", "team": "away", "continued": true },
    { "name": "More than 2.5 goals", "value": "6/7", "team": "home", "continued": true }
  ],
  "head2head": []
}
```

---

#### `GET /api/event/:eventId/goal-distributions`

Returns goal distribution by time period (1-15', 16-30', ..., 76-90') for both teams in the current season.

```json
{
  "home": {
    "goalDistributions": [
      {
        "type": "overall",
        "periods": [
          { "periodStart": 1, "periodEnd": 15, "scoredGoals": 5, "concededGoals": 3, "id": 1 }
        ],
        "matches": 32,
        "scoredGoals": 41,
        "concededGoals": 27
      },
      { "type": "home", "periods": [ ... ] },
      { "type": "away", "periods": [ ... ] }
    ]
  },
  "away": { ... }
}
```

---

#### `GET /api/event/:eventId/standings`

Returns the full league standings table for the tournament the event belongs to.

```json
{
  "standings": [
    {
      "type": "total",
      "name": "Brasileiro Serie A 2026",
      "rows": [
        {
          "position": 1,
          "team": { "id": 1963, "name": "Palmeiras", "nameCode": "PAL" },
          "matches": 8,
          "wins": 6,
          "draws": 1,
          "losses": 1,
          "scoresFor": 17,
          "scoresAgainst": 8,
          "points": 19,
          "scoreDiffFormatted": "+9",
          "promotion": { "text": "Copa Libertadores", "id": 19 }
        }
      ]
    }
  ]
}
```

---

#### `GET /api/event/:eventId/statistics`

Returns match statistics grouped by category, for the full match and each half.

| Period | Description |
|---|---|
| `ALL` | Full match |
| `1ST` | First half |
| `2ND` | Second half |

```json
{
  "statistics": [
    {
      "period": "ALL",
      "groups": [
        {
          "groupName": "Match overview",
          "statisticsItems": [
            {
              "name": "Ball possession",
              "home": "45%",
              "away": "55%",
              "homeValue": 45,
              "awayValue": 55,
              "compareCode": 2,
              "statisticsType": "positive",
              "key": "ballPossession"
            }
          ]
        }
      ]
    }
  ]
}
```

---

### Bulk & League Endpoints

#### `GET /api/:sport/odds/:date`

Returns first-market odds for all events of a sport on a given date.

```bash
GET /api/football/odds/2026-03-29
```

```json
{
  "odds": {
    "15655701": {
      "choices": [
        { "name": "1", "decimalValue": 2.10 },
        { "name": "X", "decimalValue": 3.40 },
        { "name": "2", "decimalValue": 3.20 }
      ]
    }
  }
}
```

---

#### `GET /api/leagues/:country/:sport`

Returns the default tournaments configured for a country.

```bash
GET /api/leagues/PE/football
```

```json
{
  "uniqueTournaments": [
    { "id": 406, "name": "Liga 1", "slug": "liga-1" }
  ]
}
```

---

## Programmatic API (`SofascoreRepository`)

```typescript
import { SofascoreRepository } from '@devneonix/sofascore-api';

// Fixtures
await SofascoreRepository.getFixtures('football', '2026-03-29');
await SofascoreRepository.getFixtures('football', '2026-03-29', 'PE'); // country filter

// Full match data (all in one)
await SofascoreRepository.getEventFullData('football', '15655701');

// Individual
await SofascoreRepository.getLineups('15655701');
await SofascoreRepository.getOdds('15655701');
await SofascoreRepository.getTeamStreaks('15655701');
await SofascoreRepository.getBulkOdds('football', '2026-03-29');
await SofascoreRepository.getLeagues('PE', 'football');
```

---

## Supported Sports

| Key | Sport |
|---|---|
| `football` | Football / Soccer |
| `basket` | Basketball |
| `tenis` | Tennis |

---

## Response Types

All responses are fully typed. Import interfaces directly:

```typescript
import type {
  Event,
  FullEventData,
  Lineups,
  Odds,
  StatisticsResponse,
  StandingsResponse,
  TeamStreaks,
  EventGoalDistributions,
  BulkOddsResponse,
  LeaguesData
} from '@devneonix/sofascore-api';
```

---

## License

ISC
