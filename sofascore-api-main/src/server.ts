import express from 'express';
import cors from 'cors';
import path from 'path';
import { fileURLToPath } from 'url';
import fixturesRoutes from './routes/fixtures.routes.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// API Routes
app.use('/api', fixturesRoutes);

// Static files (Frontend)
app.use(express.static(path.join(__dirname, 'views')));

app.listen(PORT, () => {
  console.log(`Server is running on http://localhost:${PORT}`);
});
