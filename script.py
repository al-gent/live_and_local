from functions import start_selenium, scrape_chapel, scrape_independent, scrape_rickshaw, parse_chapel_soups, parse_independent_soup, parse_rickshaw_soups, spotify_connect, clear_playlist, add_songs_to_playlist
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()
client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
current_date = datetime.now().date()
cutoff_in_days=21
driver = start_selenium()
chapel_soups = scrape_chapel(driver)
independent_soup = scrape_independent(driver)
rickshaw_soups = scrape_rickshaw(driver)
driver.quit()
chapel_events = parse_chapel_soups(chapel_soups, current_date=current_date, cutoff_in_days=cutoff_in_days)
ind_artists = parse_independent_soup(independent_soup, current_date=current_date, cutoff_in_days=cutoff_in_days)
rickshaw_artists = parse_rickshaw_soups(rickshaw_soups, current_date=current_date, cutoff_in_days=cutoff_in_days)
events = chapel_events + ind_artists + rickshaw_artists
sp, playlist_id = spotify_connect(client_id, client_secret)
clear_playlist(sp, playlist_id)
add_songs_to_playlist(sp, events, playlist_id)

