from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
from datetime import datetime, date
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
import html
import pandas as pd
from fuzzywuzzy import fuzz
from openai import OpenAI
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from collections import Counter
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# ============================================================================
# SETUP & DATABASE FUNCTIONS
# ============================================================================

def get_spotify_client():
    """Initialize and return Spotify client."""
    auth_manager = SpotifyOAuth(
        client_id=os.getenv('CLIENT_ID'),
        client_secret=os.getenv('CLIENT_SECRET'),
        redirect_uri="http://127.0.0.1:8080",
        scope="playlist-modify-public playlist-modify-private"
    )
    token_info = auth_manager.refresh_access_token(os.getenv('REFRESH_TOKEN'))
    return spotipy.Spotify(auth=token_info['access_token'])


def get_active_venues(cur):
    """Fetch all active venues with their configs from the database."""
    cur.execute("""
        SELECT venue_id, name, scraping_config, validation_config
        FROM venues
        WHERE is_active = TRUE
        ORDER BY name;
    """)

    column_names = [desc[0] for desc in cur.description]
    res = cur.fetchall()
    venues = [dict(zip(column_names, v)) for v in res]

    print(f"\n🎵 Found {len(venues)} active venues:")
    for venue in venues:
        print(f"   - {venue['name']}")

    return venues


# ============================================================================
# SCRAPING FUNCTIONS
# ============================================================================

def parse_date(raw_date_text, date_format):
    current_year = date.today().year
    
    # Remove ordinal suffixes (st, nd, rd, th)
    raw_date_text = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw_date_text)    
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

def scrape_venue_html(soup, venue_id, scraping_config):
    """
    Scraper for venues using HTML/CSS selectors
    Returns list of events
    """
    selectors = scraping_config['selectors']
    date_format = scraping_config['date_format']
    event_containers = soup.select(selectors['event_container'])
    
    events = []
    
    for container in event_containers:
        try:
            # Extract artists
            artist_elem = container.select_one(selectors['artist'])
            artist = artist_elem.text.strip() if artist_elem else None
            
            # Extract date
            date_elem = container.select_one(selectors['date'])
            date_text = date_elem.text.strip() if date_elem else None
            parsed_date = parse_date(date_text, date_format) if date_text else None
            
            # Extract genre (if configured)
            genre = None
            if selectors.get('genre'):
                genre_elem = container.select_one(selectors['genre'])
                genre = genre_elem.text.strip() if genre_elem else None
            
            # Check if cancelled (if configured)
            is_cancelled = False
            if selectors.get('cancellation_indicator'):
                cancel_elem = container.select_one(selectors['cancellation_indicator'])
                if cancel_elem:
                    cancelled_text = scraping_config.get('filters', {}).get('cancelled_text', 'Cancelled')
                    is_cancelled = cancel_elem.text.strip() == cancelled_text
            
            # Only add if we got at minimum an artist and date
            if artist and date_text:
                events.append({
                    'venue_id': venue_id,
                    'raw_event_name': artist,
                    'raw_date_text': date_text,
                    'genres': genre,
                    'is_cancelled': is_cancelled,
                    'parsed_date': parsed_date
                })
                
        except Exception as e:
            print(f"  ⚠️ Error parsing event: {e}")
            continue
    
    return events

def scrape_venue_json_ld(soup, venue_id, scraping_config):
    """
    Scraper for venues using JSON-LD structured data
    Returns list of events
    """
    json_keys = scraping_config.get('json_keys')
    if not json_keys:
        print(f"  ❌ Missing json_keys in config")
        return []
    
    # Find all JSON-LD script tags
    script_tags = soup.find_all('script', type='application/ld+json')
    events = []
    
    for script_tag in script_tags:
        try:
            # Clean control characters before parsing
            json_text = script_tag.string
            if json_text:
                json_text = json_text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
                event_data = json.loads(json_text)
            else:
                continue
            
            # Skip if it's not an Event schema
            if event_data.get('@type') != 'Event':
                continue
            
            # Extract artist
            artist = get_nested_value(event_data, json_keys.get('artist', 'performer'))
            artist = html.unescape(str(artist)).strip() if artist else None
            
            # Extract date
            date_string = get_nested_value(event_data, json_keys.get('date', 'startDate'))
            
            # Parse date based on format
            parsed_date = None
            date_text = None
            if date_string:
                try:
                    date_format = scraping_config.get('date_format', 'iso')
                    if date_format == 'iso':
                        # Handle various ISO formats
                        parsed_date = datetime.fromisoformat(date_string.replace('+00:00', '').replace('Z', ''))
                        date_text = parsed_date.strftime('%Y-%m-%d')
                    else:
                        parsed_date = datetime.strptime(date_string, date_format)
                        date_text = parsed_date.strftime('%Y-%m-%d')
                except Exception as e:
                    print(f"  ⚠️ Error parsing date '{date_string}': {e}")
                    date_text = date_string  # Fallback to raw string
            
            # Only add if we got at minimum an artist and date
            if artist and date_text:
                events.append({
                    'venue_id': venue_id,
                    'raw_event_name': artist,
                    'raw_date_text': date_text,
                    'genres': None,
                    'is_cancelled': False,
                    'parsed_date': parsed_date
                })
                
        except json.JSONDecodeError as e:
            print(f"  ⚠️ Skipping malformed JSON-LD script")
            continue
        except Exception as e:
            print(f"  ⚠️ Error extracting event data: {e}")
            continue
    
    return events

def get_nested_value(data, key_path):
    """
    Get value from nested dict using dot notation
    e.g., 'location.name' returns data['location']['name']
    """
    if not key_path:
        return None
        
    keys = key_path.split('.')
    value = data
    
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
            
        if value is None:
            return None
    
    return value


def scrape_all_venues(venues):
    """
    Scrape events from all active venues.

    Args:
        venues: List of venue dicts with scraping_config

    Returns:
        DataFrame with all scraped events
    """
    raw_events = []
    driver = start_selenium()

    print("\n" + "="*60)
    print("SCRAPING VENUES")
    print("="*60)

    for venue in venues:
        scraping_config = venue.get('scraping_config', {})
        venue_id = int(venue['venue_id'])
        venue_name = venue['name']

        print(f"\n🎸 Scraping {venue_name}...")

        pagination = scraping_config.get('pagination', {})

        try:
            if pagination.get('enabled'):
                # Handle paginated venues
                url_pattern = pagination.get('url_pattern')
                pages = pagination.get('pages', 1)

                for i in range(1, pages + 1):
                    page_url = url_pattern.format(page=i)
                    print(f"  → Page {i}: {page_url}")

                    try:
                        driver.get(page_url)
                        wait_time = scraping_config.get('wait_time', 1.5)
                        time.sleep(wait_time)
                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        events = scrape_venue_html(soup, venue_id, scraping_config)
                        raw_events.extend(events)
                        print(f"    ✅ Found {len(events)} events")
                    except Exception as e:
                        print(f"    ⚠️  Error on page {i}: {e}")
                        break
            else:
                # Single page venue
                base_url = scraping_config.get('base_url')
                method = scraping_config.get('scraping_method', 'html')

                driver.get(base_url)
                wait_time = scraping_config.get('wait_time', 1.5)
                time.sleep(wait_time)
                soup = BeautifulSoup(driver.page_source, 'html.parser')

                if method == 'html':
                    events = scrape_venue_html(soup, venue_id, scraping_config)
                elif method == 'json-ld':
                    events = scrape_venue_json_ld(soup, venue_id, scraping_config)
                else:
                    print(f"    ⚠️  Unknown scraping method: {method}")
                    continue

                raw_events.extend(events)
                print(f"  ✅ Found {len(events)} events")

        except Exception as e:
            print(f"  ❌ Error scraping {venue_name}: {e}")
            continue

    driver.quit()

    # Convert to DataFrame and deduplicate
    raw_df = pd.DataFrame(raw_events).drop_duplicates(['venue_id', 'raw_event_name', 'raw_date_text'])

    print(f"\n✅ Total scraped: {len(raw_df)} unique events")

    return raw_df


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_artist(sp, raw_event_name, similarity_threshold=80):
    """
    Validate a single artist name against Spotify.

    Args:
        sp: Spotipy client
        raw_event_name: Artist name to validate
        similarity_threshold: Fuzzy match threshold (0-100)

    Returns:
        dict: Validated artist data if found and matched, None otherwise
    """
    try:
        results = sp.search(q=f'artist:{raw_event_name}', type='artist', limit=3)

        if not results['artists']['items']:
            print(f"{raw_event_name} did not yield any results in a spotify search")
            return None

        spotify_artist = results['artists']['items'][0]
        name = spotify_artist['name']

        if fuzz.ratio(raw_event_name.lower(), name.lower()) < similarity_threshold:
            print(f"{raw_event_name} name did not match spotify --> {name}")
            return None

        return {
            'raw_event_name': raw_event_name,
            'spotify_artist_name': name,
            'spotify_artist_id': spotify_artist['id'],
            'artist_popularity': spotify_artist['popularity'],
            'genres': spotify_artist['genres']  # Keep as list
        }
    except Exception as e:
        print(f"❌ Error validating {raw_event_name}: {e}")
        return None


def validate_artists_parallel(sp, event_names: List[str], max_workers=4):
    """
    Validate multiple artists in parallel with rate limit protection.

    Args:
        sp: Spotipy client
        event_names: List of raw event names to validate
        max_workers: Number of parallel threads (3-4 recommended for Spotify)

    Returns:
        List of validated artist dicts
    """
    validated_artists = []

    print(f"🔍 Validating {len(event_names)} artists with {max_workers} parallel workers...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_name = {
            executor.submit(validate_artist, sp, name): name
            for name in event_names
        }

        # Collect results as they complete
        completed = 0
        for future in as_completed(future_to_name):
            result = future.result()
            if result:
                validated_artists.append(result)

            completed += 1
            # Add a tiny delay every N completions to avoid hammering the API
            if completed % (max_workers * 10) == 0:
                time.sleep(0.5)

    print(f"✅ Successfully validated {len(validated_artists)}/{len(event_names)} artists")

    return validated_artists


def parse_missed_artists_batch(unvalidated_df, batch_by_venue=True, max_batch_size=50):
    """
    Use OpenAI to filter out non-artists and split multi-artist bills.
    Batches by venue for better LLM context and to avoid token limits.

    Args:
        unvalidated_df: DataFrame with columns ['venue_id', 'raw_event_name']
        batch_by_venue: If True, process each venue separately for better context
        max_batch_size: Maximum number of artists per API call

    Returns:
        dict: Mapping of raw_event_name -> list of cleaned artist names
    """
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    all_results = {}

    if batch_by_venue:
        # Group by venue
        grouped = unvalidated_df.groupby('venue_id')['raw_event_name'].unique()

        for venue_id, artist_names in grouped.items():
            print(f"\n🎵 Processing venue {venue_id}: {len(artist_names)} events")

            # Further batch if needed (in case one venue has tons of events)
            for i in range(0, len(artist_names), max_batch_size):
                batch = artist_names[i:i + max_batch_size]
                result = _call_openai_parse(client, batch.tolist())
                if result:
                    all_results.update(result)
    else:
        # Process all at once, but still respect max batch size
        unique_artists = unvalidated_df['raw_event_name'].unique()

        for i in range(0, len(unique_artists), max_batch_size):
            batch = unique_artists[i:i + max_batch_size]
            result = _call_openai_parse(client, batch.tolist())
            if result:
                all_results.update(result)

    # Final stats
    total_filtered = sum(len(artists) for artists in all_results.values())
    total_removed = sum(1 for artists in all_results.values() if len(artists) == 0)

    print(f"\n📊 Total Input: {len(all_results)} unique raw names")
    print(f"✅ Total Output: {total_filtered} cleaned artist names")
    print(f"🗑️  Total Filtered out: {total_removed} non-artists")

    return all_results


def _call_openai_parse(client, artist_list: List[str], max_retries=3) -> Dict[str, List[str]]:
    """
    Call OpenAI API to parse artist names with error handling.

    Returns:
        dict: Mapping of raw names to cleaned artist lists, or None on failure
    """

    prompt = f"""You are analyzing a list of names scraped from music venue websites.
Some are actual musical artists/bands, and some are event names or non-musical events.

Your task: Extract and clean all PERFORMING MUSICAL ACT names.

STEP 1 - IDENTIFY if the entry contains performing musical acts:
   KEEP: Musicians, bands, DJs, tribute acts - anyone who performs music
   FILTER OUT: Event series (EMO NITE, Nerd Nite), private events, non-music events

STEP 2 - CLEAN the artist names:
   - Remove promotional text: "An Evening with", "Presented by", "Live in Concert"
   - Remove tour names: "- World Tour", "2024 Tour"
   - Remove location info: "at [venue] - [city]" (but ONLY if it's part of an artist name, not if the whole thing is an event)
   - Remove "feat.", "featuring", "with special guest" and similar

STEP 3 - SPLIT multi-artist bills:
   - "Artist A, Artist B" → ["Artist A", "Artist B"]
   - "Artist A & Artist B" → ["Artist A", "Artist B"]
   - "Artist A + Artist B" → ["Artist A", "Artist B"]
   - BUT preserve band names with natural "&" or "," (like "The Army, The Navy" or "Simon & Garfunkel" or "Andy Frasco and the U.N.")

Examples:
- "Legend Zeppelin" → ["Legend Zeppelin"]
- "EMO NITE at Rickshaw Stop - San Francisco, CA" → [] (entire thing is an event brand, filter out)
- "Nerd Nite SF" → [] (event series, filter out)
- "Nora Brown, Stephanie Coleman" → ["Nora Brown", "Stephanie Coleman"] (two artists)
- "Josh Ritter and the Royal City Band" → ["Josh Ritter and the Royal City Band"] (one act)
- "Pete Yorn – You and Me Solo Acoustic" → ["Pete Yorn"] (remove tour name)
- "Private Event" → [] (filter out)
- "Khalil, Amal, TRAVIE BOBBITO, KING MOST, BELLA D. & FRIENDS" → ["Khalil", "Amal", "TRAVIE BOBBITO", "KING MOST", "BELLA D."] (split multi-artist showcase)

Return a JSON OBJECT (not array) where:
- Keys are the original raw names from the input
- Values are arrays of cleaned artist names (empty array if filtered out)

Example output format:
{{
  "EMO NITE at Rickshaw Stop": [],
  "Nora Brown, Stephanie Coleman": ["Nora Brown", "Stephanie Coleman"],
  "XANA": ["XANA"]
}}

Names to evaluate:
{json.dumps(artist_list, indent=2)}

Respond with ONLY the JSON object, no other text."""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a music industry expert who can distinguish between artist names and event names."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}  # Force JSON response
            )

            result_text = response.choices[0].message.content.strip()

            # Clean up any markdown (shouldn't happen with json_object mode, but just in case)
            result_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', result_text.strip(), flags=re.MULTILINE)

            # Parse JSON
            filtered_mapping = json.loads(result_text)

            # Validate output structure
            if not isinstance(filtered_mapping, dict):
                raise ValueError(f"Expected dict, got {type(filtered_mapping)}")

            # Validate all values are lists
            for key, value in filtered_mapping.items():
                if not isinstance(value, list):
                    print(f"⚠️  Warning: Key '{key}' has non-list value: {value}")
                    filtered_mapping[key] = [value] if value else []

            # Stats for this batch
            total_filtered = sum(len(artists) for artists in filtered_mapping.values())
            total_removed = sum(1 for artists in filtered_mapping.values() if len(artists) == 0)

            print(f"  ✅ Batch: {len(artist_list)} input → {total_filtered} artists, {total_removed} filtered")

            return filtered_mapping

        except json.JSONDecodeError as e:
            print(f"  ⚠️  Attempt {attempt + 1}/{max_retries}: Invalid JSON response: {e}")
            if attempt == max_retries - 1:
                print(f"  ❌ Failed to parse after {max_retries} attempts")
                print(f"  Raw response: {result_text[:200]}...")
                return None

        except Exception as e:
            print(f"  ⚠️  Attempt {attempt + 1}/{max_retries}: API error: {e}")
            if attempt == max_retries - 1:
                print(f"  ❌ Failed after {max_retries} attempts")
                return None

    return None


def quick_filter_events(raw_events, validation_config):
    """
    Apply venue-specific filters BEFORE expensive API calls.

    Args:
        raw_events: DataFrame with 'raw_event_name' column
        validation_config: Dict from venues table

    Returns:
        Filtered DataFrame
    """
    if not validation_config:
        return raw_events

    filtered = raw_events.copy()
    original_count = len(filtered)

    # Remove known non-events
    non_events = validation_config.get('recurring_non_events', [])
    if non_events:
        filtered = filtered[~filtered['raw_event_name'].isin(non_events)]
        removed = original_count - len(filtered)
        if removed > 0:
            print(f"   🗑️  Filtered out {removed} known non-events")

    # Strip common text patterns (but keep original in a backup column)
    text_patterns = validation_config.get('text_patterns_to_strip', [])
    if text_patterns:
        filtered['raw_event_name_original'] = filtered['raw_event_name']
        for pattern in text_patterns:
            filtered['raw_event_name'] = filtered['raw_event_name'].str.replace(
                pattern, '', regex=False, case=False
            ).str.strip()
        print(f"   ✂️  Stripped {len(text_patterns)} common text patterns")

    return filtered


def analyze_venue_patterns(venue_id, raw_events, max_retries=3):
    """
    Use LLM to identify recurring patterns in a venue's events.
    Run this periodically (monthly) or when adding a new venue.

    Args:
        venue_id: ID of the venue to analyze
        raw_events: DataFrame with 'raw_event_name' column (all historical events)
        max_retries: Number of retries on API failure

    Returns:
        dict: validation_config to store in venues table, or None on failure
    """
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    # Get all unique event names from this venue
    event_names = raw_events['raw_event_name'].unique()

    if len(event_names) == 0:
        print(f"⚠️  No events found for venue {venue_id}")
        return None

    # Count occurrences
    event_counts = Counter(event_names)

    # Show some stats
    total_events = len(event_names)
    recurring_count = sum(1 for count in event_counts.values() if count > 1)

    print(f"\n🔍 Analyzing venue {venue_id}:")
    print(f"   Total unique events: {total_events}")
    print(f"   Recurring events: {recurring_count}")

    # Build the prompt
    prompt = f"""Analyze these event names from a music venue to identify patterns.

Context: We scrape event listings and need to filter out non-musical events and clean artist names.

Identify:
1. RECURRING NON-ARTIST EVENTS - Events that repeat (karaoke nights, open mics, private events, event series like "Emo Nite")
   - Look for things with occurrence count > 1 that aren't artists
   - Include obvious non-music events even if they only appear once ("Private Event")

2. COMMON TEXT PATTERNS TO STRIP - Text that appears in MANY event names that should be removed
   - Promotional phrases: "An Evening with", "Presents", "Live in Concert"
   - Location info: "at [venue] - [city]"
   - Tour names: "- World Tour", "Tour 2024"
   - But ONLY patterns that appear frequently (5+ times)

3. MULTI-ARTIST SEPARATOR - What character(s) does this venue use to separate multiple artists on the same bill?
   - "/" = "Artist A/ Artist B/ Artist C"
   - "," = "Artist A, Artist B, Artist C"
   - "&" = "Artist A & Artist B"
   - Look at the patterns and pick the MOST COMMON one (or null if unclear)

Event names (showing up to 100, with occurrence count):
{json.dumps({name: event_counts[name] for name in list(event_names)[:100]}, indent=2)}

IMPORTANT: Be conservative! Only flag things you're CONFIDENT about.
- Don't flag actual band names as non-events
- Don't add text patterns that only appear once or twice
- If the multi-artist separator is unclear, return null

Return ONLY valid JSON in this exact format:
{{
  "recurring_non_events": ["Karaoke Tuesday", "Private Event"],
  "text_patterns_to_strip": ["at Rickshaw Stop - San Francisco, CA"],
  "multi_artist_separator": "/"
}}"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a music industry expert analyzing venue event patterns. Be conservative and only flag obvious non-artist events."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content.strip()

            # Clean markdown just in case
            result_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', result_text.strip(), flags=re.MULTILINE)

            # Parse JSON
            patterns = json.loads(result_text)

            # Validate structure
            if not isinstance(patterns, dict):
                raise ValueError(f"Expected dict, got {type(patterns)}")

            # Ensure required keys exist
            required_keys = ['recurring_non_events', 'text_patterns_to_strip', 'multi_artist_separator']
            for key in required_keys:
                if key not in patterns:
                    patterns[key] = [] if key != 'multi_artist_separator' else None

            # Validate types
            if not isinstance(patterns['recurring_non_events'], list):
                patterns['recurring_non_events'] = []
            if not isinstance(patterns['text_patterns_to_strip'], list):
                patterns['text_patterns_to_strip'] = []

            # Add metadata
            patterns['last_pattern_analysis'] = datetime.now().isoformat()
            patterns['total_events_analyzed'] = total_events

            # Show results
            print(f"\n✅ Pattern analysis complete:")
            print(f"   Non-events to filter: {len(patterns['recurring_non_events'])}")
            print(f"   Text patterns to strip: {len(patterns['text_patterns_to_strip'])}")
            print(f"   Multi-artist separator: {patterns['multi_artist_separator']}")

            if patterns['recurring_non_events']:
                print(f"\n   Will filter out: {patterns['recurring_non_events'][:5]}{'...' if len(patterns['recurring_non_events']) > 5 else ''}")

            return patterns

        except json.JSONDecodeError as e:
            print(f"  ⚠️  Attempt {attempt + 1}/{max_retries}: Invalid JSON: {e}")
            if attempt == max_retries - 1:
                print(f"  ❌ Failed to parse after {max_retries} attempts")
                return None

        except Exception as e:
            print(f"  ⚠️  Attempt {attempt + 1}/{max_retries}: Error: {e}")
            if attempt == max_retries - 1:
                print(f"  ❌ Failed after {max_retries} attempts")
                return None

    return None
