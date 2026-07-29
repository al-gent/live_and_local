import time
from datetime import datetime, date, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import html
import pandas as pd
import os
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
import random
from dotenv import load_dotenv
from pathlib import Path

# Get the directory where the script is
script_dir = Path(__file__).parent
env_path = script_dir / '.env'
load_dotenv(env_path)
conn = psycopg2.connect(os.getenv('DATABASE_URL_UNPOOLED'))

cur = conn.cursor()

# Get all active venues
cur.execute("""
    SELECT * 
    FROM users 
""")

column_names = [desc[0] for desc in cur.description]
res = cur.fetchall()
users = [dict(zip(column_names, v)) for v in res]

cur.execute("""
    SELECT * 
    FROM playlists 
    where is_active = True
""")

column_names = [desc[0] for desc in cur.description]
res = cur.fetchall()
playlists = [dict(zip(column_names, v)) for v in res]
print('playlists')
for user in users:
    print('   ', user['display_name'])
    for playlist in playlists:
        if playlist['spotify_user_id'] == user['spotify_user_id']:
            print('       ', playlist['playlist_name'])

load_dotenv()
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')


def send_reauth_email(email, display_name):
    """Notify a user via Brevo that their Spotify connection expired."""
    api_key = os.getenv('BREVO_API_KEY')
    if not api_key or not email:
        print(f"        (no Brevo key or email — couldn't notify {display_name})")
        return
    first_name = (display_name or 'there').split()[0]
    resp = requests.post(
        'https://api.brevo.com/v3/smtp/email',
        headers={'api-key': api_key, 'Content-Type': 'application/json'},
        json={
            'sender': {'name': 'live&local', 'email': 'noreply@inverttheparadigm.com'},
            'replyTo': {'name': 'Adam Gent', 'email': '94gent@gmail.com'},
            'to': [{'email': email}],
            'subject': 'your live&local playlist needs a quick re-link 🎸',
            'htmlContent': (
                f"<p>Hey {first_name}!</p>"
                "<p>Quick heads up from the live&amp;local bot — Spotify expires app logins "
                "every 6 months now, and yours just lapsed. That means your playlist can't "
                "get its weekly update of upcoming shows until you reconnect.</p>"
                "<p>The fix takes about 10 seconds: head to "
                '<a href="https://playlist.adamlgent.com">playlist.adamlgent.com</a> '
                "and hit the Spotify sign-in again. That's it — updates resume Sunday.</p>"
                "<p>Sorry for the hassle — blame Spotify 😄</p><p>Adam</p>"
            ),
        },
        timeout=15,
    )
    if resp.ok:
        print(f"        notified {display_name} at {email}")
    else:
        print(f"        failed to notify {display_name}: {resp.status_code} {resp.text[:200]}")

notified = set()
for p in playlists:
    spotify_user_id = p['spotify_user_id']
    cur.execute("""
        SELECT DISTINCT spotify_artist_id
        FROM validated_events
        WHERE venue_id = ANY(%s)
        AND event_date > %s
        AND event_date < %s
    """, (
        p['preferred_venues'],
        date.today(),
        date.today() + timedelta(days=p['days_ahead'])
    ))

    artist_ids = [row[0] for row in cur.fetchall()]
    
    refresh_token = None
    display_name = None
    user_email = None
    for user in users:
        if user['spotify_user_id'] == spotify_user_id:
            credentials = user['spotify_credentials'] or {}
            refresh_token = credentials.get('refresh_token')
            display_name = user['display_name']
            user_email = user['email']

    if not refresh_token:
        print(f"skipping {display_name or spotify_user_id}: no Spotify credentials, user must sign in again")
        continue

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri="http://127.0.0.1:8080",
        scope="playlist-modify-public playlist-modify-private"
    )
    try:
        token_info = auth_manager.refresh_access_token(refresh_token)
    except SpotifyOauthError as e:
        # Refresh tokens expire after 6 months (Spotify policy since July 2026).
        # On invalid_grant: discard the stored token, don't retry — user must sign in again.
        if 'invalid_grant' in str(e):
            # '{}' not NULL — the column has a NOT NULL constraint
            cur.execute(
                "UPDATE users SET spotify_credentials = '{}' WHERE spotify_user_id = %s",
                (spotify_user_id,)
            )
            conn.commit()
            print(f"skipping {display_name}: refresh token expired, discarded — user must sign in again")
            if spotify_user_id not in notified:
                notified.add(spotify_user_id)
                send_reauth_email(user_email, display_name)
            continue
        raise

    # Persist a rotated refresh token so it doesn't hit the 6-month expiry
    if token_info.get('refresh_token') and token_info['refresh_token'] != refresh_token:
        credentials.update(token_info)
        cur.execute(
            "UPDATE users SET spotify_credentials = %s WHERE spotify_user_id = %s",
            (json.dumps(credentials), spotify_user_id)
        )
        conn.commit()

    sp = spotipy.Spotify(auth=token_info['access_token'])

    track_uris = []
    n = p['songs_per_artist']

    for artist_id in artist_ids:
        result = sp.artist_top_tracks(artist_id, country='US')
        tracks = random.sample(result['tracks'], min(n, len(result['tracks'])))
        track_uris.extend([track['uri'] for track in tracks])

    # Handle 100-track limit
    if len(track_uris) <= 100:
        sp.playlist_replace_items(p['playlist_id'], track_uris)
    else:
        sp.playlist_replace_items(p['playlist_id'], track_uris[:100])
        for i in range(100, len(track_uris), 100):
            sp.playlist_add_items(p['playlist_id'], track_uris[i:i+100])
    print(f'updated playlist for {display_name}')
    print(f"added {len(track_uris)} tracks from {len(artist_ids)} artists playing at {len(p['preferred_venues'])} venues")