from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import os
from selenium.common.exceptions import TimeoutException
from datetime import date


def parse_date(raw_date_text, date_format):
    current_year = date.today().year

    # Check if year is already in the format
    if '%Y' in date_format or '%y' in date_format:
        # Year is included, parse as-is
        parsed_date = datetime.strptime(raw_date_text.strip(), date_format).date()
    else:
        # No year in format, add current year
        parsed_date = datetime.strptime(f"{raw_date_text.strip()} {current_year}", f"{date_format} %Y").date()
        
        # If it's in the past, use next year
        if parsed_date < date.today():
            parsed_date = parsed_date.replace(year=current_year + 1)

    return parsed_date

def start_selenium():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.page_load_strategy = 'eager'
    chrome_options.add_argument("--disable-images")
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(10)
    return driver

def get_soup(url, driver):
    try:
        driver.get(url)
        time.sleep(1)
        html = driver.page_source
        return BeautifulSoup(html, 'html.parser')
    except TimeoutException:
        print(f"Timeout on {url}, skipping...")
        return None

def scrape_chapel(driver):
    chapel_soups = []
    for i in range(2):
        print(f'getting chapel page {i+1}')
        driver.get(f"https://thechapelsf.com/music/?list1page={i+1}")
        time.sleep(3)
        html = driver.page_source
        chapel_soups.append(BeautifulSoup(html, 'html.parser'))
    return chapel_soups

def scrape_independent(driver):
    print('getting ind')
    driver.get("https://www.theindependentsf.com/")
    time.sleep(3)
    html = driver.page_source
    independent_soup = BeautifulSoup(html, 'html.parser')
    return independent_soup

def scrape_rickshaw(driver):
    rickshaw_soups = []
    for i in range(2):
        print(f'getting rickshaw page {i+1}')
        driver.get(f"https://rickshawstop.com/?list1page={i+1}")
        time.sleep(3)
        html = driver.page_source
        rickshaw_soups.append(BeautifulSoup(html, 'html.parser'))
    return rickshaw_soups

def parse_independent_soup(independent_soup, current_date, cutoff_in_days=21):
    ind_artists = []
    for div in independent_soup.find_all('div', class_='tw-section'):
        artist = (div.find('div', class_='tw-name').find('a').text.strip())
        event_date_text = div.find('span', class_='tw-event-date').text.strip()
        date_with_year = f"{event_date_text}.{current_date.year}"
        event_date = datetime.strptime(date_with_year.strip(), "%m.%d.%Y").date()

        if event_date < current_date:
            event_date = datetime.strptime(f"{event_date_text}.{current_date.year + 1}", "%m.%d.%Y").date()
        
        days_until_event = (event_date - current_date).days
        if (0 <= days_until_event <= cutoff_in_days) and ((div.find('div', class_='tw-info-price-buy-tix').find_all('a')[1].text.strip()) != 'Cancelled'):
            ind_artists.append(artist)

    return ind_artists

def parse_chapel_soups(chapel_soups, current_date, cutoff_in_days=21):
    
    chapel_events = []
    for soup in chapel_soups:
        for div in soup.find_all('div', class_='event-info-block'):
            event_title = div.find('p', class_='fs-12 headliners').text
            event_date_text = div.find('p', class_='fs-18 bold mt-1r date').text
            genre = div.find('p', class_='fs-12 genre').text
            date_with_year = f"{event_date_text} {current_date.year}"
            event_date = datetime.strptime(date_with_year, "%a %b %d %Y").date()
            if event_date < current_date:
                event_date = datetime.strptime(f"{event_date_text} {current_date.year + 1}", "%a %b %d %Y").date()
            days_until_event = (event_date - current_date).days
            if (0 <= days_until_event <= cutoff_in_days) and (genre != 'Tribute Act') and (genre != 'Other Content') and ('Dance' not in genre) and ('DJ' not in genre) and (event_title not in chapel_events):
                chapel_events.append(event_title)
                
    return chapel_events

def parse_rickshaw_soups(rickshaw_soups, current_date, cutoff_in_days=21):

    rickshaw_events=[]
    for soup in rickshaw_soups:
        events = soup.find_all('div',class_ = 'event-info-block')
        for event in events:
            headliner = event.find('p', class_ = 'fs-12 headliners').text

            event_date_text = event.find('p', class_ = 'fs-18 bold mt-1r date').text
            date_with_year = f"{event_date_text} {current_date.year}"
            event_date = datetime.strptime(date_with_year, "%a %b %d %Y").date()

            if event_date < current_date:
                event_date = datetime.strptime(f"{event_date_text} {current_date.year + 1}", "%a %b %d %Y").date()
            days_until_event = (event_date - current_date).days
            if (0 <= days_until_event <= cutoff_in_days) and (headliner not in rickshaw_events):
                rickshaw_events.append(headliner)

    return rickshaw_events


def spotify_connect(client_id, client_secret, refresh_token, playlist_name='Live & Local'):
    print(f"Using refresh token: {refresh_token[:5]}...")
    
    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri="http://127.0.0.1:8080",
        scope="playlist-modify-public playlist-modify-private"
    )
    
    if refresh_token:
        try:
            token_info = auth_manager.refresh_access_token(refresh_token)
            print(f"Got access token: {token_info['access_token'][:5]}...")
            
            sp = spotipy.Spotify(auth=token_info['access_token'])
        except Exception as e:
            print(f"Refresh token failed: {e}")
            raise
    else:
        sp = spotipy.Spotify(auth_manager=auth_manager)
    
    user = sp.current_user()
    user = sp.current_user()
    playlists = sp.user_playlists(user['id'])
    
    playlist = None
    for p in playlists['items']:
        if p['name'] == playlist_name:
            playlist = p
            break
    
    if playlist:
        print(f"User found: {user['display_name']} \nPlaylist found: {playlist_name}")
        playlist_id = playlist['id']
    else:
        # Create the playlist if it doesn't exist
        print(f"Playlist '{playlist_name}' not found. Creating it...")
        new_playlist = sp.user_playlist_create(
            user=user['id'],
            name=playlist_name,
            public=True,
            description="Upcoming live music in SF - auto-generated"
        )
        playlist_id = new_playlist['id']
        print(f"Created playlist: {playlist_name}")

    return sp, playlist_id
    
def clear_playlist(sp, playlist_id):
    tracks = sp.playlist_tracks(playlist_id)
    track_uris = [track['track']['uri'] for track in tracks['items']]
    if track_uris:
        sp.playlist_remove_all_occurrences_of_items(playlist_id, track_uris)

def add_songs_to_playlist(sp, events, playlist_id, n=4):
    not_found=[]
    for event_name in events:
        results = sp.search(q=f'artist:{event_name}', type='artist', limit=3)
        search_result_name_id = [(k['name'], k['id']) for k in results['artists']['items']]
        if search_result_name_id:
            artist_name, artist_id = search_result_name_id[0]
            top_tracks = sp.artist_top_tracks(artist_id, country='US')
            tracks_to_add = top_tracks['tracks'][:n]
            print(artist_name)
            for track in tracks_to_add:
                print(f"        {track['name']}")
            track_uris = []
            for i, track in enumerate(tracks_to_add, 1):
                track_uris.append(track['uri'])
            sp.playlist_add_items(playlist_id, track_uris)
        else:
            not_found.append(event_name)
    print('The following artists were not found')
    for artist in not_found:
        print(artist)


