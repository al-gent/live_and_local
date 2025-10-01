import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL_UNPOOLED,
  ssl: {
    rejectUnauthorized: false
  }
});

export default async function handler(req, res) {
  if (req.method !== 'PUT') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { 
    playlist_id, 
    spotify_user_id,
    playlist_name,
    playlist_description,
    preferred_venues,
    songs_per_artist,
    days_ahead
  } = req.body;

  if (!playlist_id || !spotify_user_id) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  try {
    const result = await pool.query(
      `UPDATE playlists 
       SET 
         playlist_name = COALESCE($1, playlist_name),
         playlist_description = COALESCE($2, playlist_description),
         preferred_venues = COALESCE($3, preferred_venues),
         songs_per_artist = COALESCE($4, songs_per_artist),
         days_ahead = COALESCE($5, days_ahead),
         updated_at = NOW()
       WHERE playlist_id = $6 AND spotify_user_id = $7
       RETURNING *`,
      [
        playlist_name,
        playlist_description,
        preferred_venues,
        songs_per_artist,
        days_ahead,
        playlist_id,
        spotify_user_id
      ]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Playlist not found' });
    }

    res.status(200).json({ success: true, playlist: result.rows[0] });
  } catch (error) {
    console.error('Database error:', error);
    res.status(500).json({ error: 'Failed to update playlist' });
  }
}