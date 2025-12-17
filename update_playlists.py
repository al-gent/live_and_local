import time
from datetime import datetime, date, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import html
import pandas as pd
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
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
    
    for user in users:
        if user['spotify_user_id'] == spotify_user_id:
            refresh_token = user['spotify_credentials']['refresh_token']
            display_name = user['display_name']

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri="http://127.0.0.1:8080",
        scope="playlist-modify-public playlist-modify-private"
    )
    token_info = auth_manager.refresh_access_token(refresh_token)
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