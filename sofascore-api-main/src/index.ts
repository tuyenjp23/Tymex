import { SofascoreService } from './services/sofascore.service.js';
import type {
  FixturesResponse,
  FullEventData,
  Lineups,
  Odds,
  BulkOddsResponse,
  LeaguesData,
  TeamStreaks
} from './types/index.js';

export const SofascoreRepository = {
  /**
   * Obtiene todos los partidos (fixtures) para un deporte y fecha específicos.
   * Por defecto es global, pero se puede filtrar por país.
   */
  async getFixtures(sport: string, date: string, country?: string): Promise<FixturesResponse> {
    return SofascoreService.getFixtures(sport, date, country);
  },

  /**
   * Obtiene la información completa de un evento (Alineaciones, Odds, Info General)
   */
  async getEventFullData(sport: string, eventId: string): Promise<FullEventData> {
    const [event, odds, lineups, teamStreaks, h2hHistory, goalDistributions, standings, statistics] = await Promise.all([
      SofascoreService.getEvent(eventId).catch(() => null),
      SofascoreService.getOdds(eventId).catch(() => null),
      SofascoreService.getLineups(eventId).catch(() => null),
      SofascoreService.getTeamStreaks(eventId).catch(() => null),
      SofascoreService.getEventH2HHistory(eventId).catch(() => null),
      SofascoreService.getEventGoalDistributions(eventId).catch(() => null),
      SofascoreService.getEventStandings(eventId).catch(() => null),
      SofascoreService.getStatistics(eventId).catch(() => null)
    ]);

    return {
      event,
      odds,
      lineups,
      teamStreaks,
      h2hHistory,
      goalDistributions,
      standings,
      statistics
    };
  },

  /**
   * Obtiene alineaciones específicas
   */
  async getLineups(eventId: string): Promise<Lineups> {
    return SofascoreService.getLineups(eventId);
  },

  /**
   * Obtiene cuotas (odds) específicas
   */
  async getOdds(eventId: string): Promise<Odds> {
    return SofascoreService.getOdds(eventId);
  },

  /**
   * Obtiene cuotas en bloque para todos los partidos de un deporte/fecha
   */
  async getBulkOdds(sport: string, date: string): Promise<BulkOddsResponse> {
    return SofascoreService.getBulkOdds(sport, date);
  },

  /**
   * Obtiene la lista de torneos/ligas configurados para un país
   */
  async getLeagues(country: string, sport: string): Promise<LeaguesData> {
    return SofascoreService.getLeagues(country, sport);
  },

  /**
   * Obtiene las rachas (streaks) de los equipos local y visitante para un evento
   */
  async getTeamStreaks(eventId: string): Promise<TeamStreaks> {
    return SofascoreService.getTeamStreaks(eventId);
  }
};

export { SofascoreService };
export * from './types/index.js';
