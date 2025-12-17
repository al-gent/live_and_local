/**
 * API Endpoint: POST /api/request-venue
 * 
 * Creates a manual review request when automatic venue discovery fails
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

  const { url, requested_by, error_message, discovery_metadata } = req.body;

  // Validate required fields
  if (!url || !requested_by) {
    return res.status(400).json({ 
      error: 'Missing required fields',
      required: ['url', 'requested_by']
    });
  }

  try {
    const insertQuery = `
      INSERT INTO venue_requests (url, requested_by, error_message, discovery_metadata, status)
      VALUES ($1, $2, $3, $4, 'pending')
      RETURNING request_id, requested_at;
    `;
    
    const result = await pool.query(insertQuery, [
      url,
      requested_by,
      error_message || null,
      discovery_metadata ? JSON.stringify(discovery_metadata) : null
    ]);
    
    const { request_id, requested_at } = result.rows[0];
    
    res.status(200).json({
      success: true,
      message: 'Venue request submitted for review',
      request_id,
      requested_at
    });
    
  } catch (error) {
    console.error('Database error:', error);
    res.status(500).json({ 
      error: 'Failed to submit venue request',
      message: error.message
    });
  }
}
