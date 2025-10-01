import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL_UNPOOLED,
  ssl: {
    rejectUnauthorized: false
  }
});

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { spotify_user_id } = req.query;

  if (!spotify_user_id) {
    return res.status(400).json({ error: 'Missing spotify_user_id' });
  }

  try {
    const result = await pool.query(
      `SELECT 
        playlist_id,
        playlist_name,
        playlist_description,
        preferred_venues,
        songs_per_artist,
        days_ahead,
        is_active,
        playlist_updated_at,
        created_at
       FROM playlists 
       WHERE spotify_user_id = $1 and is_active = True
       ORDER BY created_at DESC`,
      [spotify_user_id]
    );

    res.status(200).json({ 
      playlists: result.rows,
      count: result.rows.length
    });
  } catch (error) {
    console.error('Database query error:', error);
    res.status(500).json({ error: 'Failed to fetch playlists' });
  }
}