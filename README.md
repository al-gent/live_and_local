# SF Live Music Playlist Generator

Scrapes upcoming shows from SF venues (Chapel, Independent, Rickshaw Stop) and creates a Spotify playlist with tracks from performing artists.

## Setup

1. Install dependencies:
   ```bash
   pip install selenium beautifulsoup4 spotipy python-dotenv
   ```

2. Install ChromeDriver and add to PATH

3. Create Spotify app at [developer.spotify.com](https://developer.spotify.com/dashboard)

4. Create `.env` file:
   ```
   CLIENT_ID=your_spotify_client_id
   CLIENT_SECRET=your_spotify_client_secret
   REFRESH_TOKEN=your_refresh_token
   ```

5. Create a Spotify playlist named "Live & Local"

## Usage

```bash
python main.py
```

Finds shows in next 21 days and updates your playlist with 4 tracks per artist.

## Files

- `functions.py` - Scraping and Spotify functions
- `main.py` - Main script

## Contributing
Pull requests welcome! Planning to add more venues and a user-friendly interface.