import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL_UNPOOLED,
  ssl: {
    rejectUnauthorized: false
  }
});

async function deleteSpotifyPlaylist(playlistId, accessToken) {
  const response = await fetch(`https://api.spotify.com/v1/playlists/${playlistId}/followers`, {
    method: 'DELETE',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
    }
  });
  
  return response.ok;
}

export default async function handler(req, res) {
  if (req.method !== 'DELETE') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { playlist_id, spotify_user_id } = req.body;

  if (!playlist_id || !spotify_user_id) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  try {
    // Get user's access token
    const userResult = await pool.query(
      'SELECT spotify_credentials FROM users WHERE spotify_user_id = $1',
      [spotify_user_id]
    );

    if (userResult.rows.length === 0) {
      return res.status(404).json({ error: 'User not found' });
    }

    const credentials = userResult.rows[0].spotify_credentials;
    
    // Delete from Spotify
    const spotifyDeleted = await deleteSpotifyPlaylist(playlist_id, credentials.access_token);
    
    if (!spotifyDeleted) {
      return res.status(500).json({ error: 'Failed to delete from Spotify' });
    }

    // Soft delete from database
    const result = await pool.query(
      `UPDATE playlists 
       SET is_active = false, updated_at = NOW()
       WHERE playlist_id = $1 AND spotify_user_id = $2
       RETURNING *`,
      [playlist_id, spotify_user_id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Playlist not found in database' });
    }

    res.status(200).json({ success: true, message: 'Playlist deleted from Spotify and database' });
  } catch (error) {
    console.error('Database error:', error);
    res.status(500).json({ error: 'Failed to delete playlist' });
  }
}