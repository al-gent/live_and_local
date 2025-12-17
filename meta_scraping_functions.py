"""
Meta Scraping Functions
========================
AI-powered agent for automatically generating HTML scraping configurations for venue websites.

This is the "meta" layer - it scrapes the scraping parameters themselves!
Run these functions INFREQUENTLY (when adding new venues) to generate the scraping_config
that gets stored in the database.

The actual scraping happens in populate_events_functions.py (run weekly).

This module contains:
- HTML Selector Discovery: Extract CSS selectors for event containers, artist names, and dates
"""

import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import json
import re
import os
import time
from typing import Dict, Optional, List
from datetime import date, datetime
import psycopg2

# ============================================================================
# HTML SELECTOR DISCOVERY
# ============================================================================

def get_selectors(soup: BeautifulSoup) -> Optional[Dict]:
    """
    Analyze a venue calendar page and discover CSS selectors for scraping.
    
    Uses AI to find the container, artist, and date selectors.

    Args:
        soup: BeautifulSoup object of the venue calendar page

    Returns:
        dict: Selector configuration with 'container', 'artist', 'date' keys
    """
    # Clean up the HTML first
    for tag in soup(['script', 'style', 'svg', 'iframe', 'noscript', 'meta', 'link']):
        tag.decompose()
    
    # Remove common non-content sections
    for tag in soup.find_all(['nav', 'header', 'footer']):
        tag.decompose()
    
    body = soup.find('body') or soup
    html = str(body)
    
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # cheapest model
        messages=[
            {
                "role": "system",
                "content": "You are a web scraping expert. Find CSS selectors."
            },
            {
                "role": "user", 
                "content": f"""
    Look at this HTML and tell me:
    1. The CSS selector for the container that holds each event
    2. The CSS selector for the artist name
    3. The CSS selector for the date
    HTML:
    {html[:15000]}

    Return JSON only:
    {{
    "container": "...",
    "artist": "...",
    "date": "...",
    }}
    """
            }
        ]
    )

    result_text = response.choices[0].message.content.strip()

    # Clean markdown if present
    result_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', result_text.strip(), flags=re.MULTILINE)

    # Parse JSON
    return json.loads(result_text)


def get_date_format(dates: List[str]) -> str:
    """
    Determine the Python strptime format for a list of date strings.
    
    Args:
        dates: List of raw date strings from scraping
        
    Returns:
        str: Python strptime format string or "INVALID" if dates can't be parsed
    """
    client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # cheapest model
        messages=[
            {
                "role": "system",
                "content": "You are a syntax expert specifically in dates in python. Return ONLY valid Python strptime format codes."
            },
            {
                "role": "user", 
                "content": f"""

                Look at the following dates and return JUST the Python strptime format string that fits the dates.
                IMPORTANT: Use ONLY standard Python strptime codes like %a, %A, %b, %B, %d, %m, %Y, %y, etc.
                DO NOT include literal text like 'th', 'st', 'nd', 'rd' in the format string.
                
                Examples:
                - If dates look like "Fri Oct 24", the format would be "%a %b %d"
                - If dates look like "10/24/2025", the format would be "%m/%d/%Y"
                - If dates look like "Friday October 24th", the format would be "%A %B %d" (removed 'th')
                - If dates look like "24", this cannot be parsed - return "INVALID"
                
                {dates}
                Return just the format string or "INVALID" if the dates don't have enough info.

                """
                        }
                    ]
                )

    result_text = response.choices[0].message.content.strip()

    # Clean markdown if present
    result_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', result_text.strip(), flags=re.MULTILINE)
    result_text = result_text.strip('"\'')  # Remove quotes if present
    
    return result_text


def parse_date(raw_date_text: str, date_format: str) -> date:
    """
    Parse a date string using a given format string.
    
    Args:
        raw_date_text: The raw date string to parse
        date_format: Python strptime format string
        
    Returns:
        date: Parsed date object
        
    Raises:
        ValueError: If date cannot be parsed with the given format
    """
    current_year = date.today().year
    
    # Remove ordinal suffixes (st, nd, rd, th) from the text
    raw_date_text = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', raw_date_text)
    
    # Check if year is already in the format
    has_year = '%Y' in date_format or '%y' in date_format
    has_month = '%m' in date_format or '%b' in date_format or '%B' in date_format
    
    # If format is incomplete, try to handle it
    if not has_year:
        if not has_month:
            # Only day number - this is invalid, can't parse
            raise ValueError(f"Cannot parse date '{raw_date_text}' with incomplete format '{date_format}'")
        # Has month but no year - append current year
        parsed_date = datetime.strptime(f"{raw_date_text.strip()} {current_year}", f"{date_format} %Y").date()
        # If the date is in the past, assume next year
        if parsed_date < date.today():
            parsed_date = parsed_date.replace(year=current_year + 1)
    else:
        # Full format with year
        parsed_date = datetime.strptime(raw_date_text.strip(), date_format).date()
    
    return parsed_date


def check_date_format(raw_dates: List[str], date_format: str) -> float:
    """
    Check how many dates in a list can be parsed with the given format.
    
    Args:
        raw_dates: List of raw date strings to test
        date_format: Python strptime format string to test
        
    Returns:
        float: Fraction (0.0 to 1.0) of dates that can be successfully parsed
    """
    if date_format.upper() == "INVALID":
        return 0.0
        
    c = 0
    for raw_date in raw_dates:
        try:
            parse_date(raw_date, date_format)
            c+=1
        except (ValueError, TypeError):
            pass
    return c/len(raw_dates) if raw_dates else 0.0


def get_events(soup: BeautifulSoup, selectors: Dict[str, str]) -> List[Dict]:
    """
    Extract events from HTML using the given selectors.
    
    Args:
        soup: BeautifulSoup object of the page
        selectors: Dict with 'container', 'artist', 'date' CSS selectors
        
    Returns:
        list: List of dicts with 'artist' and 'raw_date' keys
    """
    containers = soup.select(selectors['container'])

    events = []
    for container in containers:
        # Find artist and date within each container
        artist_elem = container.select_one(selectors['artist'])
        date_elem = container.select_one(selectors['date'])
        
        artist = artist_elem.get_text(strip=True) if artist_elem else None
        raw_date = date_elem.get_text(strip=True) if date_elem else None
        if artist and raw_date:
            events.append({
                'artist': artist,
                'raw_date': raw_date
            })
    return events


# ============================================================================
# MAIN ORCHESTRATOR
# ============================================================================

def discover_venue_scraping_config(url: str, use_selenium: bool = True, min_success_rate: float = 0.9) -> Optional[Dict]:
    """
    Complete pipeline to discover scraping configuration for a venue URL.
    
    This function:
    1. Fetches the URL with Selenium (for JS-rendered sites)
    2. Uses AI to find CSS selectors for events
    3. Scrapes initial events to validate
    4. Discovers the date format
    5. Validates that >90% of dates can be parsed

    Args:
        url: The venue calendar URL to analyze
        use_selenium: If True (default), use Selenium to render JavaScript (recommended for modern sites)
        min_success_rate: Minimum fraction of dates that must parse successfully (default 0.9)

    Returns:
        dict: Complete configuration ready for manual review and database insertion:
        {
            'url': 'https://...',
            'selectors': {
                'container': 'div.event-item',
                'artist': 'h2.artist-name',
                'date': 'span.date'
            },
            'date_format': '%a %b %d, %Y',
            'events': [{'artist': '...', 'raw_date': '...'}, ...],
            'validation_success': True/False,
            'num_events_found': 10,
            'date_parse_success_rate': 0.95
        }
        Returns None if configuration discovery fails.
    """
    print("\n" + "="*70)
    print("VENUE SCRAPING CONFIGURATION DISCOVERY")
    print("="*70)
    print(f"\n🎵 Analyzing: {url}")
    
    # STEP 1: Fetch the page
    print(f"\n📥 Fetching URL...")
    if use_selenium:
        print("   Using Selenium (JavaScript rendering enabled)...")
        try:
            from populate_events_functions import start_selenium
            driver = start_selenium()
            driver.get(url)
            time.sleep(3)  # Wait for JS to load
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            driver.quit()
        except Exception as e:
            print(f"❌ Failed to fetch with Selenium: {e}")
            return None
    else:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"❌ Failed to fetch URL: {e}")
            return None

    # STEP 2: Discover CSS selectors
    print(f"\n🔍 Discovering CSS selectors...")
    selectors = get_selectors(soup)
    if not selectors:
        print("❌ Failed to discover selectors")
        return None

    print(f"   Container: {selectors['container']}")
    print(f"   Artist: {selectors['artist']}")
    print(f"   Date: {selectors['date']}")
    
    # STEP 3: Extract events using the selectors
    print(f"\n🎯 Scraping events...")
    events = get_events(soup, selectors)
    num_events = len(events)
    print(f"   Found {num_events} events")
    
    if num_events == 0:
        print("❌ No events found - selectors may be incorrect")
        return None
    
    # Show sample events
    for i, event in enumerate(events[:3], 1):
        print(f"   {i}. {event['artist'][:50]} - {event['raw_date']}")
    
    # STEP 4: Discover date format
    print(f"\n📅 Discovering date format...")
    dates = [event['raw_date'] for event in events]
    date_format = get_date_format(dates)
    print(f"   Format detected: {date_format}")
    
    # STEP 5: Validate date parsing
    print(f"\n✅ Validating date parsing...")
    success_rate = check_date_format(dates, date_format)
    print(f"   Success rate: {success_rate:.2%}")
    
    is_valid = success_rate >= min_success_rate
    
    # Build result
    result = {
        'url': url,
        'selectors': selectors,
        'date_format': date_format,
        'events': events,
        'validation_success': is_valid,
        'num_events_found': num_events,
        'date_parse_success_rate': success_rate,
        'use_selenium': use_selenium
    }
    
    if is_valid:
        print(f"\n🎉 Configuration discovery successful!")
        print(f"   ✅ Found {num_events} events")
        print(f"   ✅ Date format validated ({success_rate:.2%} success)")
    else:
        print(f"\n⚠️  Configuration needs review")
        print(f"   ⚠️  Date parse rate below threshold ({success_rate:.2%} < {min_success_rate:.2%})")
    
    return result


def format_for_database(config_result: Dict) -> Dict:
    """
    Convert the config result from discover_venue_scraping_config into a format
    suitable for storing in the venues table scraping_config column.
    
    Note: Pagination is set to enabled=None (unknown) and need_to_configure=True
    because pagination detection is a separate concern handled during
    the a next step. We will need to configure pagination after the initial config is discovered.
    
    Args:
        config_result: Result from discover_venue_scraping_config()
        
    Returns:
        dict: Database-ready scraping_config format
    """
    return {
        "base_url": config_result['url'],
        "scraping_method": "html",
        "use_selenium": config_result.get('use_selenium', True),
        "selectors": {
            "event_container": config_result['selectors']['container'],
            "artist": config_result['selectors']['artist'],
            "date": config_result['selectors']['date']
        },
        "date_format": config_result['date_format'],
        "pagination": {
            "enabled": None,
            "need_to_configure": True
        },
        "_metadata": {
            "auto_generated": True,
            "validation_success": config_result['validation_success'],
            "num_events_found": config_result['num_events_found'],
            "date_parse_success_rate": config_result['date_parse_success_rate'],
            "discovered_at": datetime.now().isoformat()
        }
    }

def add_venue_to_db(name, city, url, scraping_config, address=None):
    """
    Insert or update venue in the database.
    
    Args:
        name: Venue name
        city: City where venue is located
        url: Venue website/calendar URL (used as unique key)
        scraping_config: Dict with scraping configuration (will be stored as JSONB)
        address: Optional street address
        
    Returns:
        int: The venue_id of the inserted/updated venue
        
    Raises:
        Exception: If database insertion fails
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL_UNPOOLED'))
    cur = conn.cursor()
    
    insert_query = """
    INSERT INTO venues (name, address, city, url, scraping_config)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (url) DO UPDATE SET
        name = EXCLUDED.name,
        address = EXCLUDED.address,
        city = EXCLUDED.city,
        scraping_config = EXCLUDED.scraping_config,
        updated_at = CURRENT_TIMESTAMP
    RETURNING venue_id, name;
    """
    
    try:
        cur.execute(insert_query, (
            name,
            address,
            city,
            url,
            json.dumps(scraping_config)
        ))
        
        venue_id, venue_name = cur.fetchone()
        conn.commit()
        
        print(f"✅ Successfully added/updated: {venue_name} (ID: {venue_id})")
        return venue_id
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()
