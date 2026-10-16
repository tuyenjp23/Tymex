import type { Request, Response } from 'express';
import { SofascoreService } from '../services/sofascore.service.js';
import type {
  Event,
  FixturesResponse,
  BulkOddsResponse,
  Lineups,
  Odds,
  LeaguesData,
  FullEventData,
  PartialEventDetails,
  TeamStreaks,
  EventGoalDistributions,
  StandingsResponse,
  StatisticsResponse
} from '../types/index.js';

export class FixturesController {
  static async getFixtures(req: Request, res: Response) {
    const sport = req.params.sport as string;
    const dateStr = req.params.date as string;
    const country = req.query.country as string; // Optional: ?country=PE
    
    console.log(`[CONTROLLER] Received request for fixtures: ${sport} - ${dateStr}${country ? ` (Country: ${country})` : ' (GLOBAL)'}`);

    // Validate date format (YYYY-MM-DD)
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateStr || !dateRegex.test(dateStr)) {
      console.warn(`[CONTROLLER] Warning: Invalid date format: ${dateStr}`);
      return res.status(400).json({ error: 'Invalid date format. Expected YYYY-MM-DD' });
    }

    try {
      const [fixturesData, oddsData]: [FixturesResponse, BulkOddsResponse] = await Promise.all([
        SofascoreService.getFixtures(sport, dateStr, country),
        SofascoreService.getBulkOdds(sport, dateStr)
      ]);

      const enrichedEvents = (fixturesData.events || []).map((event: Event) => ({
        ...event,
        odds: (oddsData.odds || {})[event.id] || null
      }));

      console.log(`[CONTROLLER] Successfully returning ${enrichedEvents.length} enriched fixtures for ${sport} - ${dateStr}`);
      res.json({ events: enrichedEvents });
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getLineups(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for lineups: eventId ${eventId}`);

    try {
      const lineups: Lineups = await SofascoreService.getLineups(eventId);
      console.log(`[CONTROLLER] Successfully returning lineups for eventId ${eventId}`);
      res.json(lineups);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getOdds(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for odds: eventId ${eventId}`);

    try {
      const odds: Odds = await SofascoreService.getOdds(eventId);
      console.log(`[CONTROLLER] Successfully returning odds for eventId ${eventId}`);
      res.json(odds);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getEventDetails(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for full event details: eventId ${eventId}`);

    try {
      // Fetch everything in parallel on the backend
      const [lineups, odds]: [Lineups, Odds] = await Promise.all([
        SofascoreService.getLineups(eventId),
        SofascoreService.getOdds(eventId)
      ]);

      console.log(`[CONTROLLER] Successfully returning unified details for eventId ${eventId}`);
      const response: PartialEventDetails = { lineups, odds };
      res.json(response);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error fetching event details: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getFullEventData(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for ALL match data: eventId ${eventId}`);

    try {
      const response = await SofascoreService.getFullEventData(eventId);
      console.log(`[CONTROLLER] Successfully returning full data package for eventId ${eventId}`);
      res.json(response);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error fetching full event data: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getBulkOdds(req: Request, res: Response) {
    const sport = req.params.sport as string;
    const date = req.params.date as string;
    console.log(`[CONTROLLER] Received request for bulk odds: ${sport} - ${date}`);

    try {
      const odds: BulkOddsResponse = await SofascoreService.getBulkOdds(sport, date);
      res.json(odds);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getStatistics(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for statistics: eventId ${eventId}`);

    try {
      const data: StatisticsResponse = await SofascoreService.getStatistics(eventId);
      console.log(`[CONTROLLER] Successfully returning statistics for eventId ${eventId}`);
      res.json(data);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getStandings(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for standings: eventId ${eventId}`);

    try {
      const data: StandingsResponse = await SofascoreService.getEventStandings(eventId);
      console.log(`[CONTROLLER] Successfully returning standings for eventId ${eventId}`);
      res.json(data);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getGoalDistributions(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for goal distributions: eventId ${eventId}`);

    try {
      const data: EventGoalDistributions = await SofascoreService.getEventGoalDistributions(eventId);
      console.log(`[CONTROLLER] Successfully returning goal distributions for eventId ${eventId}`);
      res.json(data);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getTeamStreaks(req: Request, res: Response) {
    const eventId = req.params.eventId as string;
    console.log(`[CONTROLLER] Received request for team streaks: eventId ${eventId}`);

    try {
      const streaks: TeamStreaks = await SofascoreService.getTeamStreaks(eventId);
      console.log(`[CONTROLLER] Successfully returning team streaks for eventId ${eventId}`);
      res.json(streaks);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }

  static async getLeagues(req: Request, res: Response) {
    const country = req.params.country as string;
    const sport = req.params.sport as string;
    console.log(`[CONTROLLER] Received request for leagues: ${country} - ${sport}`);

    try {
      const leagues: LeaguesData = await SofascoreService.getLeagues(country, sport);
      res.json(leagues);
    } catch (error: any) {
      console.error(`[CONTROLLER] Error: ${error.message}`);
      res.status(500).json({ error: error.message });
    }
  }
}

