import axios from 'axios';
import { fractionToDecimal } from '../utils/odds.utils.js';
import type {
  FixturesResponse,
  LeaguesData,
  Lineups,
  Event,
  Odds,
  BulkOddsResponse,
  Market,
  Category,
  UniqueTournament,
  SofascorePlayerResponse,
  Player,
  TeamStreaks,
  H2HHistoryResponse,
  GoalDistributionResponse,
  EventGoalDistributions,
  StandingsResponse,
  StatisticsResponse,
  FullEventData
} from '../types/index.js';

const SOFASCORE_API_URL = 'https://api.sofascore.com/api/v1';
const SOFASCORE_WEB_API_URL = 'https://www.sofascore.com/api/v1';

export class SofascoreService {
  private static headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Origin': 'https://www.sofascore.com',
    'Referer': 'https://www.sofascore.com/',
  };

  // Fetch events for a deduplicated list of tournament IDs in parallel batches
  private static async fetchEventsForTournaments(
    tournamentIds: number[],
    date: string,
    batchSize: number = 30
  ): Promise<Event[]> {
    const allEvents: Event[] = [];

    const fetchFn = async (id: number): Promise<Event[]> => {
      try {
        const response = await axios.get(
          `${SOFASCORE_API_URL}/unique-tournament/${id}/scheduled-events/${date}`,
          { headers: this.headers, timeout: 10000 }
        );
        return response.data.events || [];
      } catch (err: any) {
        if (err.response?.status === 404) return [];
        console.warn(`[SERVICE] Warning: Could not fetch events for tournament ${id}: ${err.message}`);
        return [];
      }
    };

    for (let i = 0; i < tournamentIds.length; i += batchSize) {
      const batch = tournamentIds.slice(i, i + batchSize);
      const batchResults = await Promise.all(batch.map(fetchFn));
      batchResults.forEach(events => allEvents.push(...events));
    }

    return allEvents;
  }

  private static transformOddsMarkets(markets: any[]): Market[] {
    if (!markets) return [];
    return markets
      .filter((market: any) => market?.isLive === false)
      .map(market => ({
      ...market,
      choices: (market.choices || []).map((choice: any) => ({
        ...choice,
        decimalValue: fractionToDecimal(choice.fractionalValue, choice.value)
      }))
    }));
  }

  static async getFixtures(sport: string, date: string, country?: string): Promise<FixturesResponse> {
    const sportMap: { [key: string]: string } = {
      'football': 'football',
      'basket': 'basketball',
      'tenis': 'tennis'
    };
    const ssSport = sportMap[sport.toLowerCase()] || sport.toLowerCase();

    console.log(`[SERVICE] Fetching fixtures for sport: ${sport}, date: ${date}${country ? ` (country: ${country})` : ''}`);

    try {
      // ── Phase 1: Page through scheduled-tournaments in batches of 5 ──
      // Only the LAST page of each batch determines whether to continue.
      const PAGE_BATCH = 5;
      const allScheduled: any[] = [];
      let nextPage = 1;
      let keepGoing = true;

      while (keepGoing) {
        const pageNums = Array.from({ length: PAGE_BATCH }, (_, i) => nextPage + i);
        const pageResults = await Promise.allSettled(
          pageNums.map(p =>
            axios.get(
              `${SOFASCORE_API_URL}/sport/${ssSport}/scheduled-tournaments/${date}/page/${p}`,
              { headers: this.headers, timeout: 15000 }
            )
          )
        );

        // Collect scheduled items from all successful responses
        for (const result of pageResults) {
          if (result.status === 'fulfilled') {
            const items: any[] = result.value.data.scheduled || [];
            allScheduled.push(...items);
          }
        }

        // Continuation is determined only by the LAST page of the batch
        const lastResult = pageResults[pageResults.length - 1];
        if (!lastResult || lastResult.status === 'rejected') {
          // 404 or network error on last page — stop
          keepGoing = false;
        } else {
          const lastData = (lastResult as PromiseFulfilledResult<any>).value.data;
          keepGoing = !!(lastData.hasNextPage) && (lastData.scheduled || []).length > 0;
        }

        nextPage += PAGE_BATCH;
      }

      console.log(`[SERVICE] Collected ${allScheduled.length} scheduled tournament entries — extracting unique IDs`);

      // ── Phase 2: Extract unique tournament IDs ──
      const tournamentIds = new Set<number>();
      allScheduled.forEach(item => {
        const id = item.tournament?.uniqueTournament?.id;
        if (id) tournamentIds.add(id);
      });

      console.log(`[SERVICE] Fetching events for ${tournamentIds.size} unique tournaments in parallel`);

      // ── Phase 3: Fetch events per tournament in parallel batches ──
      const allEvents = await this.fetchEventsForTournaments([...tournamentIds], date);

      // Deduplicate events
      const uniqueMap = new Map<number, Event>();
      allEvents.forEach(ev => uniqueMap.set(ev.id, ev));
      let events = Array.from(uniqueMap.values());

      console.log(`[SERVICE] Fetched ${events.length} unique events for ${sport} on ${date}`);

      // Country filter: resolve allowed tournament IDs and filter in-memory
      if (country && country.toUpperCase() !== 'ALL') {
        const leaguesData: LeaguesData = await this.getLeagues(country, ssSport);
        const allowedIds = new Set((leaguesData.uniqueTournaments || []).map((t: UniqueTournament) => t.id));
        events = events.filter((e: Event) => {
          const tid = e.tournament?.uniqueTournament?.id ?? e.tournament?.id;
          return allowedIds.has(tid);
        });
        console.log(`[SERVICE] Filtered to ${events.length} events for country: ${country}`);
      }

      return { events };
    } catch (error: any) {
      console.error(`[SERVICE] Error fetching fixtures for ${sport} on ${date}. Reason: ${error.message}`);
      throw new Error(`Could not fetch fixtures: ${error.message}`);
    }
  }

  static async getLeagues(country: string, sport: string): Promise<LeaguesData> {
    console.log(`[SERVICE] Fetching leagues for country: ${country}, sport: ${sport}`);
    try {
      const sportMap: { [key: string]: string } = {
        'football': 'football',
        'basket': 'basketball',
        'tenis': 'tennis'
      };

      const ssSport = sportMap[sport.toLowerCase()] || sport.toLowerCase();
      const code = country.toUpperCase();
      
      const response = await axios.get(`${SOFASCORE_API_URL}/config/default-unique-tournaments/${code}/${ssSport}`, {
        headers: this.headers
      });

      console.log(`[SERVICE] Success: Fetched leagues for ${country} / ${sport}`);
      return response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch leagues for ${country} / ${sport}. Reason: ${error.message}`);
      throw new Error(`Could not fetch leagues: ${error.message}`);
    }
  }

  private static flattenPlayer(playerObj: SofascorePlayerResponse | (Player & { player?: never })): Player {
    if (!playerObj || !('player' in playerObj)) return playerObj as Player;
    const { player, ...rest } = playerObj;
    return { ...player, ...rest } as Player;
  }

  private static transformLineups(lineups: any): Lineups {
    if (!lineups) return lineups;
    const sides: (keyof Lineups)[] = ['home', 'away'];
    const transformed = { ...lineups };

    sides.forEach(side => {
      if (transformed[side]) {
        // Flatten all players first
        const allPlayers = (transformed[side].players || []).map(this.flattenPlayer);
        const subsArray = (transformed[side].substitutes || []).map(this.flattenPlayer);

        // If substitutes array is empty, it might be because they are mixed in allPlayers
        // In football they often use 'substitute: true'
        // In basketball they often use 'starter: true'
        if (subsArray.length === 0 && allPlayers.length > 0) {
          const hasStarterInfo = allPlayers.some((p: any) => p.starter !== undefined);
          const hasSubstituteInfo = allPlayers.some((p: any) => p.substitute !== undefined);

          if (hasStarterInfo) {
            transformed[side].players = allPlayers.filter((p: any) => p.starter);
            transformed[side].substitutes = allPlayers.filter((p: any) => !p.starter);
          } else if (hasSubstituteInfo) {
            transformed[side].players = allPlayers.filter((p: any) => !p.substitute);
            transformed[side].substitutes = allPlayers.filter((p: any) => p.substitute);
          } else {
            // Fallback: everyone is a player (probably just a list)
            transformed[side].players = allPlayers;
            transformed[side].substitutes = [];
          }
        } else {
          transformed[side].players = allPlayers;
          transformed[side].substitutes = subsArray;
        }

        transformed[side].missingPlayers = (transformed[side].missingPlayers || []).map(this.flattenPlayer);
      }
    });

    return transformed as Lineups;
  }

  static async getLineups(eventId: string): Promise<Lineups> {
    console.log(`[SERVICE] Fetching lineups for eventId: ${eventId}`);
    try {
      const response = await axios.get(`${SOFASCORE_API_URL}/event/${eventId}/lineups`, {
        headers: this.headers
      });
      console.log(`[SERVICE] Success: Fetched and flattened lineups for eventId: ${eventId}`);
      return this.transformLineups(response.data);
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch lineups for event ${eventId}. Reason: ${error.message}`);
      throw new Error(`Could not fetch lineups: ${error.message}`);
    }
  }

  static async getEvent(eventId: string): Promise<Event | null> {
    console.log(`[SERVICE] Fetching general info for eventId: ${eventId}`);
    try {
      const response = await axios.get(`${SOFASCORE_API_URL}/event/${eventId}`, {
        headers: this.headers
      });
      console.log(`[SERVICE] Success: Fetched general info for eventId: ${eventId}`);
      return response.data.event || response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch event info for ${eventId}. Reason: ${error.message}`);
      return null;
    }
  }

  static async getOdds(eventId: string): Promise<Odds> {
    console.log(`[SERVICE] Fetching odds for eventId: ${eventId}`);
    try {
      const response = await axios.get(`${SOFASCORE_API_URL}/event/${eventId}/odds/1/all`, {
        headers: this.headers
      });
      
      const transformedMarkets = this.transformOddsMarkets(response.data.markets);
      console.log(`[SERVICE] Success: Fetched and transformed odds for eventId: ${eventId}`);
      return { ...response.data, markets: transformedMarkets };
    } catch (error: any) {
      if (error.response && error.response.status === 404) {
        console.log(`[SERVICE] Info: No odds available (404) for eventId: ${eventId}`);
        return { markets: [] };
      }
      console.error(`[SERVICE] Error: Could not fetch odds for event ${eventId}. Reason: ${error.message}`);
      return { markets: [] };
    }
  }

  static async getGoalDistributions(teamId: number, tournamentId: number, seasonId: number): Promise<GoalDistributionResponse> {
    console.log(`[SERVICE] Fetching goal distributions for team ${teamId}, tournament ${tournamentId}, season ${seasonId}`);
    try {
      const response = await axios.get(
        `${SOFASCORE_API_URL}/team/${teamId}/unique-tournament/${tournamentId}/season/${seasonId}/goal-distributions`,
        { headers: this.headers }
      );
      console.log(`[SERVICE] Success: Fetched goal distributions for team ${teamId}`);
      return response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch goal distributions for team ${teamId}. Reason: ${error.message}`);
      throw new Error(`Could not fetch goal distributions: ${error.message}`);
    }
  }

  static async getEventGoalDistributions(eventId: string): Promise<EventGoalDistributions> {
    console.log(`[SERVICE] Fetching goal distributions for eventId: ${eventId}`);
    const event = await this.getEvent(eventId);
    if (!event) throw new Error(`Event ${eventId} not found`);

    const tournamentId = event.tournament?.uniqueTournament?.id as number;
    const seasonId = event.season?.id as number;
    const homeTeamId = event.homeTeam?.id as number;
    const awayTeamId = event.awayTeam?.id as number;

    if (!tournamentId || !seasonId) throw new Error('Missing tournament or season data in event');

    const [home, away] = await Promise.all([
      this.getGoalDistributions(homeTeamId, tournamentId, seasonId),
      this.getGoalDistributions(awayTeamId, tournamentId, seasonId)
    ]);

    return { home, away };
  }

  static async getStandings(tournamentId: number, seasonId: number): Promise<StandingsResponse> {
    console.log(`[SERVICE] Fetching standings for tournament ${tournamentId}, season ${seasonId}`);
    try {
      const response = await axios.get(
        `${SOFASCORE_API_URL}/tournament/${tournamentId}/season/${seasonId}/standings/total`,
        { headers: this.headers }
      );
      console.log(`[SERVICE] Success: Fetched standings for tournament ${tournamentId}`);
      return response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch standings. Reason: ${error.message}`);
      throw new Error(`Could not fetch standings: ${error.message}`);
    }
  }

  static async getEventStandings(eventId: string): Promise<StandingsResponse> {
    const event = await this.getEvent(eventId);
    if (!event) throw new Error(`Event ${eventId} not found`);

    const tournamentId = event.tournament?.id as number;
    const seasonId = event.season?.id as number;

    if (!tournamentId || !seasonId) throw new Error('Missing tournament or season data in event');

    return this.getStandings(tournamentId, seasonId);
  }

  static async getStatistics(eventId: string): Promise<StatisticsResponse> {
    console.log(`[SERVICE] Fetching statistics for eventId: ${eventId}`);
    try {
      const response = await axios.get(`${SOFASCORE_API_URL}/event/${eventId}/statistics`, {
        headers: this.headers
      });
      console.log(`[SERVICE] Success: Fetched statistics for eventId: ${eventId}`);
      return response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch statistics for event ${eventId}. Reason: ${error.message}`);
      throw new Error(`Could not fetch statistics: ${error.message}`);
    }
  }

  static async getTeamStreaks(eventId: string): Promise<TeamStreaks> {
    console.log(`[SERVICE] Fetching team streaks for eventId: ${eventId}`);
    try {
      const response = await axios.get(`${SOFASCORE_API_URL}/event/${eventId}/team-streaks`, {
        headers: this.headers
      });
      console.log(`[SERVICE] Success: Fetched team streaks for eventId: ${eventId}`);
      return response.data;
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch team streaks for event ${eventId}. Reason: ${error.message}`);
      throw new Error(`Could not fetch team streaks: ${error.message}`);
    }
  }

  static async getTeamLastEvents(teamId: number, limit: number = 10): Promise<Event[]> {
    console.log(`[SERVICE] Fetching last events for teamId: ${teamId}`);
    try {
      const response = await axios.get(`${SOFASCORE_WEB_API_URL}/team/${teamId}/events/last/0`, {
        headers: this.headers
      });

      const events = (response.data?.events || []) as Event[];
      return events.slice(0, Math.max(1, limit));
    } catch (error: any) {
      console.warn(`[SERVICE] Warning: Could not fetch team history for team ${teamId}. Reason: ${error.message}`);
      return [];
    }
  }

  static async getTeamNextEvents(teamId: number, limit: number = 10): Promise<Event[]> {
    console.log(`[SERVICE] Fetching next events for teamId: ${teamId}`);
    try {
      const response = await axios.get(`${SOFASCORE_WEB_API_URL}/team/${teamId}/events/next/0`, {
        headers: this.headers
      });

      const events = (response.data?.events || []) as Event[];
      return events.slice(0, Math.max(1, limit));
    } catch (error: any) {
      console.warn(`[SERVICE] Warning: Could not fetch upcoming events for team ${teamId}. Reason: ${error.message}`);
      return [];
    }
  }

  static async getEventH2HEvents(eventIdOrCustomId: string): Promise<Event[]> {
    console.log(`[SERVICE] Fetching between-teams H2H events for eventId/customId: ${eventIdOrCustomId}`);
    try {
      const response = await axios.get(`${SOFASCORE_WEB_API_URL}/event/${eventIdOrCustomId}/h2h/events`, {
        headers: this.headers
      });
      return (response.data?.events || []) as Event[];
    } catch (error: any) {
      console.warn(`[SERVICE] Warning: Could not fetch H2H events for ${eventIdOrCustomId}. Reason: ${error.message}`);
      return [];
    }
  }

  static async getEventH2HHistory(eventId: string, limitPerTeam: number = 10): Promise<H2HHistoryResponse> {
    console.log(`[SERVICE] Fetching H2H history package for eventId: ${eventId}`);

    const event = await this.getEvent(eventId);
    const homeTeamId = event?.homeTeam?.id;
    const awayTeamId = event?.awayTeam?.id;
    const h2hKey = event?.customId || eventId;

    if (!homeTeamId || !awayTeamId) {
      return {
        home: { last: [], next: [] },
        away: { last: [], next: [] },
        between: []
      };
    }

    const [homeLast, homeNext, awayLast, awayNext, between] = await Promise.all([
      this.getTeamLastEvents(homeTeamId, limitPerTeam),
      this.getTeamNextEvents(homeTeamId, limitPerTeam),
      this.getTeamLastEvents(awayTeamId, limitPerTeam),
      this.getTeamNextEvents(awayTeamId, limitPerTeam),
      this.getEventH2HEvents(String(h2hKey))
    ]);

    return {
      home: { last: homeLast, next: homeNext },
      away: { last: awayLast, next: awayNext },
      between
    };
  }

  static async getBulkOdds(sport: string, date: string): Promise<BulkOddsResponse> {
    console.log(`[SERVICE] Fetching bulk odds for sport: ${sport}, date: ${date}`);
    try {
      const sportMap: { [key: string]: string } = {
        'football': 'football',
        'basket': 'basketball',
        'tenis': 'tennis'
      };
      const ssSport = sportMap[sport.toLowerCase()] || sport.toLowerCase();

      const response = await axios.get(`${SOFASCORE_API_URL}/sport/${ssSport}/odds/1/${date}`, {
        headers: this.headers
      });

      // Transform bulk odds object
      const allOdds = response.data.odds || {};
      const transformedBulkOdds: { [key: string]: Market } = {};

      for (const eventId in allOdds) {
        const market = allOdds[eventId];
        if (market && typeof market === 'object') {
          if (market.isLive !== false) {
            continue;
          }

          transformedBulkOdds[eventId] = {
            ...market,
            choices: (market.choices || []).map((choice: any) => ({
              ...choice,
              decimalValue: fractionToDecimal(choice.fractionalValue, choice.value)
            }))
          };
        }
      }

      console.log(`[SERVICE] Success: Fetched and transformed bulk odds for ${sport} on ${date}`);
      return { ...response.data, odds: transformedBulkOdds };
    } catch (error: any) {
      console.error(`[SERVICE] Error: Could not fetch bulk odds. Reason: ${error.message}`);
      return { odds: {} };
    }
  }

  static async getFullEventData(eventId: string): Promise<FullEventData> {
    console.log(`[SERVICE] Fetching full event data for eventId: ${eventId}`);
    const [event, odds, lineups, teamStreaks, h2hHistory, goalDistributions, standings, statistics] = await Promise.all([
      this.getEvent(eventId).catch(() => null),
      this.getOdds(eventId).catch(() => null),
      this.getLineups(eventId).catch(() => null),
      this.getTeamStreaks(eventId).catch(() => null),
      this.getEventH2HHistory(eventId).catch(() => null),
      this.getEventGoalDistributions(eventId).catch(() => null),
      this.getEventStandings(eventId).catch(() => null),
      this.getStatistics(eventId).catch(() => null)
    ]);
    console.log(`[SERVICE] Success: Fetched full event data for eventId: ${eventId}`);
    return { event, odds, lineups, teamStreaks, h2hHistory, goalDistributions, standings, statistics };
  }
}


