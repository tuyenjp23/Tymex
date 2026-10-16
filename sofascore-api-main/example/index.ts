import express from 'express';
import { SofascoreRepository } from '@devneonix/sofascore-api';

const app = express();
const port = 4000;

app.get('/test-fixtures', async (req, res) => {
  try {
    const sport = (req.query.sport as string) || 'football';
    const date = (req.query.date as string) || '2026-03-11';
    
    console.log(`[EXAMPLE] Fetching fixtures for ${sport} on ${date}...`);
    const data = await SofascoreRepository.getFixtures(sport, date);
    
    res.json({
      success: true,
      count: data.events?.length || 0,
      firstMatch: data.events?.[0]?.homeTeam?.name + ' vs ' + data.events?.[0]?.awayTeam?.name,
      events: data.events?.slice(0, 5) // Send just a few for the demo
    });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/test-match/:id', async (req, res) => {
  try {
    const eventId = req.params.id;
    console.log(`[EXAMPLE] Fetching full data for match ${eventId}...`);
    
    const data = await SofascoreRepository.getEventFullData('football', eventId);
    
    res.json({
      success: true,
      hasLineups: !!data.lineups,
      hasOdds: !!data.odds,
      match: data.event?.homeTeam?.name + ' vs ' + data.event?.awayTeam?.name
    });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/test-team-streaks/:id', async (req, res) => {
  try {
    const eventId = req.params.id;
    console.log(`[EXAMPLE] Fetching team streaks for match ${eventId}...`);

    const data = await SofascoreRepository.getTeamStreaks(eventId);

    res.json({
      success: true,
      homeTeamStreaks: data.homeTeamStreaks,
      awayTeamStreaks: data.awayTeamStreaks
    });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.listen(port, () => {
  console.log(`Example app listening at http://localhost:${port}`);
  console.log(`Try: http://localhost:${port}/test-fixtures?sport=football&date=2026-03-11`);
  console.log(`Try: http://localhost:${port}/test-team-streaks/14083466`);
});
