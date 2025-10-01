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
    const result = await pool.query(`
      SELECT v.*, COUNT(ae.id) as show_count
      FROM venues v
      LEFT JOIN artist_events ae ON v.venue_id = ae.venue_id
        AND ae.event_date >= CURRENT_DATE
        AND ae.event_date <= CURRENT_DATE + INTERVAL '90 days'
      WHERE v.is_active = true
      GROUP BY v.venue_id
      ORDER BY v.city, v.name
    `);

    // Return the venues
    res.status(200).json(result.rows);
  } catch (error) {
    console.error('Database query error:', error);
    res.status(500).json({ error: 'Failed to fetch venues' });
  }
}