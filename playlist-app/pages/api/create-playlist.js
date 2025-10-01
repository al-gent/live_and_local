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

  const { 
    spotify_user_id, 
    playlist_name, 
    playlist_description, 
    preferred_venues, 
    songs_per_artist,
    days_ahead = 21  // Default to 21 days if not provided
  } = req.body;

  if (!spotify_user_id || !playlist_name || !preferred_venues?.length) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  try {
    // 1. Get user's Spotify credentials from database
    const userQuery = 'SELECT spotify_credentials, display_name FROM users WHERE spotify_user_id = $1';
    const userResult = await pool.query(userQuery, [spotify_user_id]);
    
    if (!userResult.rows.length) {
      return res.status(404).json({ error: 'User not found' });
    }

    const { spotify_credentials, display_name } = userResult.rows[0];
    let accessToken = spotify_credentials.access_token;

    // 2. Create Spotify playlist
    const createPlaylistResponse = await fetch(`https://api.spotify.com/v1/users/${spotify_user_id}/playlists`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: playlist_name,
        description: playlist_description,
        public: true
      })
    });

    if (!createPlaylistResponse.ok) {
      // Try to refresh token if it failed
      if (createPlaylistResponse.status === 401) {
        accessToken = await refreshSpotifyToken(spotify_credentials.refresh_token, spotify_user_id);
        
        // Retry playlist creation
        const retryResponse = await fetch(`https://api.spotify.com/v1/users/${spotify_user_id}/playlists`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            name: playlist_name,
            description: playlist_description,
            public: true
          })
        });

        if (!retryResponse.ok) {
          throw new Error('Failed to create Spotify playlist after token refresh');
        }

        const playlistData = await retryResponse.json();
        const spotifyPlaylistId = playlistData.id;
      } else {
        throw new Error('Failed to create Spotify playlist');
      }
    } else {
      const playlistData = await createPlaylistResponse.json();
      var spotifyPlaylistId = playlistData.id;
    }

    // 3. Save playlist to database
    const insertPlaylistQuery = `
      INSERT INTO playlists (
        playlist_id, spotify_user_id, playlist_name, playlist_description,
        preferred_venues, songs_per_artist, days_ahead
      ) VALUES ($1, $2, $3, $4, $5, $6, $7)
      RETURNING *
    `;
    
    const playlistResult = await pool.query(insertPlaylistQuery, [
      spotifyPlaylistId,
      spotify_user_id,
      playlist_name,
      playlist_description,
      preferred_venues,
      songs_per_artist,
      days_ahead
    ]);

    // 4. Get upcoming events for selected venues
    const eventsQuery = `
      SELECT DISTINCT spotify_artist_id, spotify_artist_name 
      FROM artist_events 
      WHERE venue_id = ANY($1) 
        AND event_date >= CURRENT_DATE 
        AND event_date <= CURRENT_DATE + INTERVAL '${days_ahead} days'
        AND spotify_artist_id IS NOT NULL
    `;
    
    const eventsResult = await pool.query(eventsQuery, [preferred_venues]);
    const artists = eventsResult.rows;

    if (artists.length === 0) {
      return res.status(200).json({ 
        message: 'Playlist created but no upcoming events found for selected venues',
        playlist_id: spotifyPlaylistId 
      });
    }

    // 5. Add songs to playlist
    const trackUris = [];
    
    for (const artist of artists) {
      try {
        // Get artist's top tracks
        const topTracksResponse = await fetch(
          `https://api.spotify.com/v1/artists/${artist.spotify_artist_id}/top-tracks?market=US`,
          {
            headers: { 'Authorization': `Bearer ${accessToken}` }
          }
        );

        if (topTracksResponse.ok) {
          const topTracks = await topTracksResponse.json();
          const tracksToAdd = topTracks.tracks.slice(0, songs_per_artist);
          
          for (const track of tracksToAdd) {
            trackUris.push(track.uri);
          }
        }
      } catch (error) {
        console.error(`Error getting tracks for artist ${artist.spotify_artist_name}:`, error);
        // Continue with other artists
      }
    }

    // Add tracks to playlist in batches (Spotify API limit is 100 tracks per request)
    if (trackUris.length > 0) {
      for (let i = 0; i < trackUris.length; i += 100) {
        const batch = trackUris.slice(i, i + 100);
        
        await fetch(`https://api.spotify.com/v1/playlists/${spotifyPlaylistId}/tracks`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({ uris: batch })
        });
      }
    }

    // 6. Update playlist record with last update time
    await pool.query(
      'UPDATE playlists SET playlist_updated_at = CURRENT_TIMESTAMP WHERE playlist_id = $1',
      [spotifyPlaylistId]
    );

    res.status(200).json({ 
      message: 'Playlist created successfully',
      playlist_id: spotifyPlaylistId,
      tracks_added: trackUris.length,
      artists_found: artists.length
    });

  } catch (error) {
    console.error('Create playlist error:', error);
    res.status(500).json({ error: 'Failed to create playlist' });
  }
}

async function refreshSpotifyToken(refreshToken, userId) {
  const tokenResponse = await fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Authorization': `Basic ${Buffer.from(
        `${process.env.NEXT_PUBLIC_SPOTIFY_CLIENT_ID}:${process.env.SPOTIFY_CLIENT_SECRET}`
      ).toString('base64')}`
    },
    body: new URLSearchParams({
      grant_type: 'refresh_token',
      refresh_token: refreshToken
    })
  });

  if (!tokenResponse.ok) {
    throw new Error('Failed to refresh Spotify token');
  }

  const newTokens = await tokenResponse.json();
  
  // Update user's credentials in database
  await pool.query(
    'UPDATE users SET spotify_credentials = $1 WHERE spotify_user_id = $2',
    [JSON.stringify(newTokens), userId]
  );

  return newTokens.access_token;
}