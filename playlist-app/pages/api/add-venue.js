/**
 * API Endpoint: POST /api/add-venue
 * 
 * Adds a new venue to the database after user confirmation
 */

import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL_UNPOOLED,
  ssl: {
    rejectUnauthorized: false
  }
});

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { name, city, url, address, scraping_config } = req.body;

  // Validate required fields
  if (!name || !city || !url || !scraping_config) {
    return res.status(400).json({ 
      error: 'Missing required fields',
      required: ['name', 'city', 'url', 'scraping_config']
    });
  }

  try {
    const insertQuery = `
      INSERT INTO venues (name, address, city, url, scraping_config)
      VALUES ($1, $2, $3, $4, $5)
      ON CONFLICT (url) DO UPDATE SET
        name = EXCLUDED.name,
        address = EXCLUDED.address,
        city = EXCLUDED.city,
        scraping_config = EXCLUDED.scraping_config,
        updated_at = CURRENT_TIMESTAMP
      RETURNING venue_id, name;
    `;
    
    const result = await pool.query(insertQuery, [
      name,
      address || null,
      city,
      url,
      JSON.stringify(scraping_config)
    ]);
    
    const { venue_id, name: venue_name } = result.rows[0];
    
    res.status(200).json({
      success: true,
      message: 'Venue added successfully',
      venue_id,
      venue_name
    });
    
  } catch (error) {
    console.error('Database error:', error);
    res.status(500).json({ 
      error: 'Failed to add venue',
      message: error.message
    });
  }
}
