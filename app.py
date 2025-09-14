from flask import Flask, redirect, session, request, render_template
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from dotenv import load_dotenv
from functions import start_selenium
from scrape_functions import get_artists_from_url

# eventually we'll want to load this from a db
known_classes = {'http://www.thechapelsf.com': "fs-12 headliners"}

app = Flask(__name__)
app.secret_key = 'my-local-dev-key-2024'


# Spotify config
load_dotenv()
refresh_token = os.getenv('REFRESH_TOKEN')
SPOTIFY_CLIENT_ID = os.getenv('CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:5000/callback' 
venues= []
driver = start_selenium()


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope="playlist-modify-public playlist-modify-private"
    )

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login')
def login():
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/callback')
def callback():
    sp_oauth = create_spotify_oauth()
    
    # Get the authorization code from Spotify
    code = request.args.get('code')
    
    # Exchange code for tokens
    token_info = sp_oauth.get_access_token(code)
    
    # Save tokens in session
    session['token_info'] = token_info
    
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    token_info = session.get('token_info')
    if not token_info:
        return redirect('/login')
    
    sp = spotipy.Spotify(auth=token_info['access_token'])

    user = sp.current_user()
    session['user'] = user

    
    venues = session.get('user_venues', [])  # Empty list if none
    return render_template('dashboard.html', user=user,  venues=venues)

@app.route('/create-playlist', methods=['POST'])
def create_playlist():
    venue_url = request.form.get('venue_url')
    print(f"Original URL: {venue_url}")
    
    if venue_url and not venue_url.startswith(('http://', 'https://')):
        if venue_url.startswith('www.'):
            venue_url = 'https://' + venue_url
        else:
            venue_url = 'https://www.' + venue_url
    
    print(f"--------***---------Final URL: {venue_url}")
    artists = get_artists_from_url(venue_url, driver, known_classes)

    if artists:
        venues.append(venue_url)
        return render_template('success.html', 
                         artists=artists)
    else:
        return render_template('dashboard.html',
                               user=session['user'],
                               message='Failed to scrape artists')


if __name__ == '__main__':
    app.run(debug=True)