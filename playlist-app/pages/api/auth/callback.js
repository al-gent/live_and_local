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

  const { code, state, error } = req.query;

  // Handle user denying access
  if (error) {
    return res.redirect('/?error=access_denied');
  }

  // Verify state parameter for security (you'll need to implement state generation)
  if (!code) {
    return res.redirect('/?error=no_code');
  }

  try {
    // Exchange authorization code for access tokens
    const tokenResponse = await fetch('https://accounts.spotify.com/api/token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Authorization': `Basic ${Buffer.from(
          `${process.env.NEXT_PUBLIC_SPOTIFY_CLIENT_ID}:${process.env.SPOTIFY_CLIENT_SECRET}`
        ).toString('base64')}`
      },
      body: new URLSearchParams({
        grant_type: 'authorization_code',
        code: code,
        redirect_uri: process.env.REDIRECT_URI
      })
    });

  if (!tokenResponse.ok) {
      throw new Error('Failed to exchange code for tokens');
    }

    const tokens = await tokenResponse.json();

    // Get user info from Spotify
    const userResponse = await fetch('https://api.spotify.com/v1/me', {
      headers: {
        'Authorization': `Bearer ${tokens.access_token}`
      }
    });

    if (!userResponse.ok) {
      const errorBody = await userResponse.text();
      console.error('Spotify user info failed:', {
        status: userResponse.status,
        statusText: userResponse.statusText,
        body: errorBody
      });
      throw new Error(`Failed to fetch user info: ${userResponse.status} ${errorBody}`);
    }

    const spotifyUser = await userResponse.json();

    // Store or update user in database
    const userQuery = `
      INSERT INTO users (spotify_user_id, display_name, email, spotify_credentials)
      VALUES ($1, $2, $3, $4)
      ON CONFLICT (spotify_user_id) 
      DO UPDATE SET 
        display_name = EXCLUDED.display_name,
        email = EXCLUDED.email,
        spotify_credentials = EXCLUDED.spotify_credentials,
        updated_at = CURRENT_TIMESTAMP
      RETURNING *
    `;

    const userResult = await pool.query(userQuery, [
      spotifyUser.id,
      spotifyUser.display_name,
      spotifyUser.email,
      JSON.stringify(tokens)
    ]);

    // Set session cookie or JWT token here
    // For now, we'll redirect with user info in URL params (not secure, just for testing)
    const userData = encodeURIComponent(JSON.stringify({
      id: spotifyUser.id,
      display_name: spotifyUser.display_name,
      email: spotifyUser.email
    }));

    res.redirect(`/?user=${userData}`);

  } catch (error) {
    console.error('OAuth callback error:', error);
    res.redirect('/?error=auth_failed');
  }
}