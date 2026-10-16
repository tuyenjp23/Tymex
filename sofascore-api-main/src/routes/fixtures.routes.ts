import { Router } from 'express';
import { FixturesController } from '../controllers/fixtures.controller.js';

const router = Router();

router.get('/:sport/fixtures/:date', (req, res) => {
  FixturesController.getFixtures(req, res);
});

router.get('/event/:eventId/lineups', (req, res) => {
  FixturesController.getLineups(req, res);
});

router.get('/event/:eventId/odds', (req, res) => {
  FixturesController.getOdds(req, res);
});

router.get('/event/:eventId/details', (req, res) => {
  FixturesController.getEventDetails(req, res);
});

router.get('/event/:eventId/team-streaks', (req, res) => {
  FixturesController.getTeamStreaks(req, res);
});

router.get('/event/:eventId/goal-distributions', (req, res) => {
  FixturesController.getGoalDistributions(req, res);
});

router.get('/event/:eventId/standings', (req, res) => {
  FixturesController.getStandings(req, res);
});

router.get('/event/:eventId/statistics', (req, res) => {
  FixturesController.getStatistics(req, res);
});

// New endpoint for full data (General + Odds + Lineups)
router.get('/:sport/:eventId/full-data', (req, res) => {
  FixturesController.getFullEventData(req, res);
});

router.get('/:sport/odds/:date', (req, res) => {
  FixturesController.getBulkOdds(req, res);
});

router.get('/leagues/:country/:sport', (req, res) => {
  FixturesController.getLeagues(req, res);
});

export default router;
