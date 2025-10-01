from openai import OpenAI
from bs4 import BeautifulSoup
import time
from selenium.common.exceptions import TimeoutException
import re
import spotipy
from spotipy.oauth2 import SpotifyOAuth

def spotify_connect(client_id, client_secret, refresh_token= None, playlist_name='Live & Local'):
    
    if refresh_token:
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

def validate_url(venue_url):
    if not venue_url.startswith(('http://', 'https://')):
        if venue_url.startswith('www.'):
            venue_url = 'https://' + venue_url
        else:
            venue_url = 'https://www.' + venue_url
    return venue_url

def get_soup(url, driver):
    try:
        driver.get(url)
        time.sleep(3)
        html = driver.page_source
        return BeautifulSoup(html, 'html.parser')
    except TimeoutException:
        print(f"Timeout on {url}, skipping...")
        return None

def parse_soup(soup, tag_class):
    artist_soup = soup.select(f'[class*="{tag_class}"]')
    return [artist.text.strip() for artist in artist_soup]


def whats_the_class(soup, failed_class=None):
    client = OpenAI()
    html_str = str(soup)[:15000]
    
    failed_message = f"I already tried '{failed_class}' and it didn't work - don't suggest that again.\n" if failed_class else ''
    
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "system",
            "content": "You are an expert at analyzing HTML structure. Return only the CSS class name(s) used for headliner/artist names, nothing else."
        }, {
            "role": "user",
            "content": f"""Analyze this venue website HTML and find the CSS class used specifically for headliner/artist names.
            {failed_message}
            Look for patterns like:
            - Elements containing artist names
            - Event titles with performer names
            - Headliner sections
            Return ONLY the class name(s). Examples:
            event-title
            artist-name headliner
            fs-12 rhp-event__title

            HTML:
            {html_str}"""
                    }],
                    temperature=0,
                    max_tokens=50
                )
    return completion.choices[0].message.content.strip()

def parse_venue_flow(venue_url, venue_soup, known_classes):
    # if you know the class to 
    if known_classes.get(venue_url):
        print('I already know the tags this website uses!')
        tag_class = known_classes[venue_url]
        headliners = parse_soup(venue_soup, tag_class)
        return headliners
    # else ask chat for the tag
    print('I never parsed this site before! let me ask chat what the class is')
    chat_says = whats_the_class(venue_soup)
    print('chat thinks the class is', chat_says)
    headliners = parse_soup(venue_soup, chat_says)

    if headliners and len(headliners) > 0:
        print(f'found {len(headliners)} headliners, saving class')
        known_classes[venue_url] = chat_says
        return headliners
    print('The tag chat gave me didnt work, let me try again!')
    chat_says_2 = whats_the_class(venue_soup, failed_class=chat_says)
    print('chat thinks the tag is', chat_says_2)
    headliners = parse_soup(venue_soup, chat_says_2)

    if headliners and len(headliners) > 0:
        print(f'found {len(headliners)} headliners, saving class')
        known_classes[venue_url] = chat_says
        return headliners
    else:
        print('chat failed twice - give up 😡😡')
        return None


def clean_headliners(headliners):
    """Take a list of headliners and return a list that is cleaner"""
    # OKAY NEW CHALLENGE is to parse through these event titles / headliners and find them on spotify
    # skip ones that are obviously not bands
    print('CLEANING')
    skips = ['open mic', 'karaoke', 'stand up']
    drops =  ["tour", "with", "presented by", "featuring", 'presents']

    # Create a single regex pattern for skips (faster than multiple string searches)
    skip_pattern = re.compile('|'.join(skips), re.IGNORECASE)

    # Create a single regex pattern for drops
    drop_pattern = re.compile('|'.join(re.escape(drop) for drop in drops), re.IGNORECASE)

    cleaned_headliners = []

    for headliner in headliners:
        # Single regex search instead of loop
        if skip_pattern.search(headliner):
            print(f"Skipping: {headliner}")
            continue
        
        # Single regex substitution instead of multiple replacements
        cleaned = drop_pattern.sub('', headliner).strip()
        if cleaned != headliner: 
            print(headliner,'|||', cleaned)
        if cleaned:
            cleaned_headliners.append(cleaned)
    return cleaned_headliners


def find_artist_on_spotify(sp, headliner):
    search_results={'strict':[], 'loose':[]}
    strict_search = sp.search(q=f'artist:{headliner}', type='artist', limit=3)
    search_result_name_id = [(k['name'], k['id']) for k in strict_search['artists']['items']]

    if search_result_name_id:
        artist_name, artist_id = search_result_name_id[0]
        # print('strict', headliner, '---->', artist_name)
        search_results['strict'].append([headliner, artist_name])
    else: 
        loose_search = sp.search(q=headliner, type='artist', limit=3)

        search_result_name_id = [(k['name'], k['id']) for k in loose_search['artists']['items']]
        if search_result_name_id:
            artist_name, artist_id = search_result_name_id[0]
            # print('loose', headliner, '---->', artist_name)
            search_results['loose'].append([headliner, artist_name])

    return artist_name, artist_id

def add_songs_from_artist(sp, artist_id, playlist_id, n=3, country_code='US', actually_add=True):
    top_tracks = sp.artist_top_tracks(artist_id, country=country_code)
    tracks_to_add = top_tracks['tracks'][:n]
    track_uris = [track['uri'] for track in tracks_to_add]
    if actually_add:
        sp.playlist_add_items(playlist_id, track_uris)
        print(len(track_uris), 'songs added')
    else:
        print(len(track_uris), 'songs ready to add')

