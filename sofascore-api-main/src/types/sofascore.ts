export interface Tournament {
  id: number;
  name: string;
  slug: string;
  category: Category;
  uniqueTournament?: UniqueTournament;
}

export interface Category {
  id: number;
  name: string;
  slug: string;
  sport: Sport;
}

export interface Sport {
  id: number;
  name: string;
  slug: string;
}

export interface UniqueTournament {
  id: number;
  name: string;
  slug: string;
  category: Category;
}

export interface Team {
  id: number;
  name: string;
  slug: string;
  shortName: string;
  nameCode: string;
  type: number;
}

export interface Status {
  code: number;
  description: string;
  type: string;
}

export interface Event {
  id: number;
  slug: string;
  name: string;
  status: Status;
  homeTeam: Team;
  awayTeam: Team;
  homeScore?: Score;
  awayScore?: Score;
  startTimestamp: number;
  tournament: Tournament;
  [key: string]: any;
}

export interface Score {
  current?: number;
  display?: number;
  period1?: number;
  period2?: number;
  normaltime?: number;
}

export interface Choice {
  name: string;
  description?: string;
  fractionalValue: string;
  sourceId: number;
  value: number;
  decimalValue?: number;
}

export interface Market {
  id: number;
  name: string;
  isMain: boolean;
  choices: Choice[];
}

export interface Odds {
  markets: Market[];
  [key: string]: any;
}

export interface PlayerDetails {
  id: number;
  name: string;
  slug: string;
  shortName: string;
  position: string;
  jerseyNumber: string;
  userCount?: number;
  marketValueCurrency?: string;
  dateOfBirthTimestamp?: number;
  fieldTranslations?: any;
}

export interface Player extends PlayerDetails {
  starter?: boolean;
  substitute?: boolean;
  statistics?: any;
  [key: string]: any;
}

export interface SofascorePlayerResponse {
  player: PlayerDetails;
  position: string;
  jerseyNumber: string;
  starter?: boolean;
  substitute?: boolean;
  statistics?: any;
  [key: string]: any;
}

export interface LineupSide {
  players: Player[];
  substitutes: Player[];
  missingPlayers: Player[];
  formation?: string;
  captain?: Player;
}

export interface Lineups {
  home: LineupSide;
  away: LineupSide;
  confirmed?: boolean;
}

export interface LeaguesData {
  uniqueTournaments: UniqueTournament[];
  [key: string]: any;
}

export interface FixturesResponse {
  events: Event[];
}

export interface FullEventData {
  event: Event | null;
  odds: Odds | null;
  lineups: Lineups | null;
  teamStreaks: TeamStreaks | null;
  h2hHistory: H2HHistoryResponse | null;
  goalDistributions: EventGoalDistributions | null;
  standings: StandingsResponse | null;
  statistics: StatisticsResponse | null;
}

export interface TeamHistory {
  last: Event[];
  next: Event[];
}

export interface H2HHistoryResponse {
  home: TeamHistory;
  away: TeamHistory;
  between: Event[];
}

export interface PartialEventDetails {
  lineups: Lineups | null;
  odds: Odds;
}

export interface BulkOddsResponse {
  odds: { [eventId: string]: Market };
  [key: string]: any;
}

export interface StatisticItem {
  key: string;
  name: string;
  home: string;
  away: string;
  homeValue: number;
  awayValue: number;
  homeTotal?: number;
  awayTotal?: number;
  compareCode: number;
  statisticsType: 'positive' | 'negative';
  valueType: 'event' | 'team';
  renderType: number;
}

export interface StatisticGroup {
  groupName: string;
  statisticsItems: StatisticItem[];
}

export interface StatisticPeriod {
  period: 'ALL' | '1ST' | '2ND';
  groups: StatisticGroup[];
}

export interface StatisticsResponse {
  statistics: StatisticPeriod[];
}

export interface StandingTeamColors {
  primary: string;
  secondary: string;
  text: string;
}

export interface StandingTeam {
  id: number;
  name: string;
  slug: string;
  shortName: string;
  nameCode: string;
  type: number;
  teamColors: StandingTeamColors;
}

export interface StandingPromotion {
  id: number;
  text: string;
}

export interface TieBreakingRule {
  id: number;
  text: string;
}

export interface StandingRow {
  id: number;
  team: StandingTeam;
  position: number;
  matches: number;
  wins: number;
  draws: number;
  losses: number;
  scoresFor: number;
  scoresAgainst: number;
  points: number;
  scoreDiffFormatted: string;
  descriptions: any[];
  promotion?: StandingPromotion;
}

export interface Standing {
  id: number;
  type: string;
  name: string;
  rows: StandingRow[];
  descriptions: any[];
  tieBreakingRule?: TieBreakingRule;
  tournament: Tournament;
  updatedAtTimestamp: number;
}

export interface StandingsResponse {
  standings: Standing[];
}

export interface GoalDistributionPeriod {
  id: number;
  periodStart: number;
  periodEnd: number;
  scoredGoals: number;
  concededGoals: number;
}

export interface GoalDistribution {
  id: number;
  type: 'home' | 'away' | 'overall';
  periods: GoalDistributionPeriod[];
  matches: number;
  scoredGoals: number;
  concededGoals: number;
}

export interface GoalDistributionResponse {
  goalDistributions: GoalDistribution[];
}

export interface EventGoalDistributions {
  home: GoalDistributionResponse;
  away: GoalDistributionResponse;
}

export interface TeamStreak {
  name: string;
  value: string;
  team: 'home' | 'away';
  continued: boolean;
}

export interface TeamStreaks {
  general: TeamStreak[];
  head2head: TeamStreak[];
}
