import { Pool } from 'pg';

// Create a connection pool
const pool = new Pool({
  connectionString: process.env.DATABASE_URL_UNPOOLED,
  ssl: {
    rejectUnauthorized: false
  }
});

export default async function handler(req, res) {
  // Only allow GET requests
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    // Query the database
    const result = await pool.query(
      'SELECT venue_id, name, address, city, url FROM venues WHERE is_active = TRUE ORDER BY name'
    );

    // Return the venues
    res.status(200).json(result.rows);

  } catch (error) {
    console.error('Database query error:', error);
    res.status(500).json({ error: 'Failed to fetch venues' });
  }
}