#!/usr/bin/env python3
"""
Populate Events Script
======================
Scrapes venues, validates artists, and populates the validated_events table.

This script:
1. Scrapes events from all active venues
2. Filters out known non-events using validation_config
3. Validates artists against Spotify API
4. Uses OpenAI to parse multi-artist bills and clean event names
5. Inserts validated events into the database
6. Logs validation failures for debugging

Usage:
    python populate_events.py
"""

import os
import psycopg2
import psycopg2.extras
import pandas as pd
from dotenv import load_dotenv

from populate_events_functions import (
    get_spotify_client,
    get_active_venues,
    scrape_all_venues,
    validate_artists_parallel,
    parse_missed_artists_batch,
    quick_filter_events
)

# Load environment variables
load_dotenv()


def filter_events(raw_df, venues):
    """Apply venue-specific validation configs to filter out known non-events."""
    print("\n" + "="*60)
    print("PRE-FILTERING WITH VALIDATION CONFIGS")
    print("="*60)

    all_filtered_events = []

    for venue in venues:
        venue_id = int(venue['venue_id'])
        validation_config = venue.get('validation_config', {})

        print(f"\n🎵 Processing {venue['name']}")

        venue_raw_events = raw_df[raw_df['venue_id'] == venue_id].copy()

        if len(venue_raw_events) == 0:
            print(f"   ⚠️  No events found")
            continue

        print(f"   📊 Found {len(venue_raw_events)} raw events")

        # Apply quick filters
        filtered_events_df = quick_filter_events(venue_raw_events, validation_config)
        print(f"   ✅ After pre-filtering: {len(filtered_events_df)} events remain")

        all_filtered_events.append(filtered_events_df)

    # Combine all venues
    filtered_df = pd.concat(all_filtered_events, ignore_index=True)

    print(f"\n📊 Total: {len(raw_df)} raw events → {len(filtered_df)} after pre-filtering")

    return filtered_df


def validate_events(filtered_df, sp):
    """Validate events in two rounds: direct Spotify match, then LLM parsing."""
    print("\n" + "="*60)
    print("VALIDATION - ROUND 1 (Direct Spotify Match)")
    print("="*60)

    # Round 1: Direct validation
    unique_names = filtered_df['raw_event_name'].unique().tolist()
    validated_artists_list = validate_artists_parallel(sp, unique_names, max_workers=4)
    validated_df = pd.DataFrame(validated_artists_list)

    # Merge with event data to get full schema
    validated_df = filtered_df[['venue_id', 'raw_event_name', 'raw_date_text', 'parsed_date', 'is_cancelled']].merge(
        validated_df,
        on='raw_event_name',
        how='inner'
    )

    # Format for DB schema
    validated_df = validated_df.rename(columns={'parsed_date': 'event_date'})
    validated_df['genres'] = validated_df['genres'].apply(
        lambda x: ','.join(x) if isinstance(x, list) and x else None
    )

    print(f"\n✅ Round 1: Validated {len(validated_df)} events")

    # Find unvalidated events
    validated_names = set(validated_df['raw_event_name'])
    unvalidated_df = filtered_df[~filtered_df['raw_event_name'].isin(validated_names)]

    if len(unvalidated_df) == 0:
        print("\n🎉 All events validated in Round 1!")
        return validated_df

    # Round 2: LLM parsing + validation
    print("\n" + "="*60)
    print("VALIDATION - ROUND 2 (LLM Parsing)")
    print("="*60)

    print(f"\n📊 {len(unvalidated_df)} events need LLM parsing")

    event_artist_map = parse_missed_artists_batch(unvalidated_df, batch_by_venue=False)

    # Flatten and validate cleaned artists
    all_cleaned_artists = [artist for artists_list in event_artist_map.values() for artist in artists_list]
    unique_cleaned_artists = list(set(all_cleaned_artists))

    print(f"\n   {len(all_cleaned_artists)} total artists → {len(unique_cleaned_artists)} unique")

    validated_artists_list = validate_artists_parallel(sp, unique_cleaned_artists, max_workers=4)
    validated_artists_dict = {v['raw_event_name']: v for v in validated_artists_list}

    # Build additional rows
    new_rows = []
    for raw_event_name, cleaned_artists in event_artist_map.items():
        original_events = unvalidated_df[unvalidated_df['raw_event_name'] == raw_event_name]
        if original_events.empty:
            continue

        original_event = original_events.iloc[0]

        for cleaned_artist_name in cleaned_artists:
            if cleaned_artist_name in validated_artists_dict:
                validated = validated_artists_dict[cleaned_artist_name]

                new_row = {
                    'venue_id': original_event['venue_id'],
                    'event_date': original_event['parsed_date'],
                    'spotify_artist_id': validated['spotify_artist_id'],
                    'spotify_artist_name': validated['spotify_artist_name'],
                    'artist_popularity': validated['artist_popularity'],
                    'genres': ','.join(validated['genres']) if validated['genres'] else None,
                    'raw_event_name': raw_event_name,
                    'raw_date_text': original_event['raw_date_text'],
                    'is_cancelled': original_event.get('is_cancelled', False)
                }
                new_rows.append(new_row)

    additional_validated_df = pd.DataFrame(new_rows)

    # Combine both rounds
    validated_df = pd.concat([validated_df, additional_validated_df], ignore_index=True)

    # Deduplicate
    validated_df = validated_df.drop_duplicates(
        subset=['venue_id', 'spotify_artist_id', 'event_date'],
        keep='first'
    )

    print(f"\n✅ Round 2: Validated {len(additional_validated_df)} additional events")
    print(f"🎉 Total validated: {len(validated_df)} events")

    return validated_df


def insert_to_database(validated_df, raw_df, filtered_df, cur, conn):
    """Insert validated events and failures to database."""
    print("\n" + "="*60)
    print("DATABASE INSERTION")
    print("="*60)

    # 1. Insert validated events
    insert_validated_query = """
    INSERT INTO validated_events (
        venue_id,
        event_date,
        spotify_artist_id,
        spotify_artist_name,
        artist_popularity,
        genres,
        raw_event_name,
        is_cancelled
    ) VALUES %s
    ON CONFLICT (venue_id, spotify_artist_id, event_date)
    DO UPDATE SET
        artist_popularity = EXCLUDED.artist_popularity,
        genres = EXCLUDED.genres,
        raw_event_name = EXCLUDED.raw_event_name,
        is_cancelled = EXCLUDED.is_cancelled,
        scraped_at = CURRENT_TIMESTAMP
    """

    validated_tuples = []
    for _, row in validated_df.iterrows():
        validated_tuple = (
            int(row['venue_id']),
            row['event_date'],
            row['spotify_artist_id'],
            row['spotify_artist_name'],
            int(row['artist_popularity']) if pd.notna(row['artist_popularity']) else None,
            row['genres'],
            row['raw_event_name'],
            bool(row['is_cancelled'])
        )
        validated_tuples.append(validated_tuple)

    psycopg2.extras.execute_values(
        cur,
        insert_validated_query,
        validated_tuples,
        template=None,
        page_size=100
    )

    print(f"✅ Inserted {len(validated_tuples)} validated events")

    # 2. Track validation failures
    validated_raw_names = set(validated_df['raw_event_name'].unique())
    failed_events = filtered_df[~filtered_df['raw_event_name'].isin(validated_raw_names)].copy()
    pre_filtered_events = raw_df[~raw_df['raw_event_name'].isin(filtered_df['raw_event_name'])].copy()

    failed_events['failure_reason'] = 'spotify_not_found_or_mismatch'
    pre_filtered_events['failure_reason'] = 'filtered_pre_validation'

    all_failures_df = pd.concat([failed_events, pre_filtered_events], ignore_index=True)

    if len(all_failures_df) > 0:
        insert_failures_query = """
        INSERT INTO validation_failures (
            venue_id,
            raw_event_name,
            raw_date_text,
            event_date,
            failure_reason
        ) VALUES %s
        """

        failure_tuples = []
        for _, row in all_failures_df.iterrows():
            failure_tuple = (
                int(row['venue_id']),
                row['raw_event_name'],
                row.get('raw_date_text'),
                row.get('parsed_date') if pd.notna(row.get('parsed_date')) else None,
                row['failure_reason']
            )
            failure_tuples.append(failure_tuple)

        psycopg2.extras.execute_values(
            cur,
            insert_failures_query,
            failure_tuples,
            template=None,
            page_size=100
        )

        print(f"⚠️  Logged {len(failure_tuples)} validation failures")

    # Commit everything
    conn.commit()

    print(f"\n🎉 Database update complete!")
    print(f"   ✅ {len(validated_tuples)} validated events")
    print(f"   ❌ {len(all_failures_df) if len(all_failures_df) > 0 else 0} failures logged")


def main():
    """Main execution flow."""
    print("\n" + "="*60)
    print("🎸 POPULATE EVENTS - Starting Script")
    print("="*60)

    # Initialize connections
    conn = psycopg2.connect(os.getenv('DATABASE_URL_UNPOOLED'))
    cur = conn.cursor()
    sp = get_spotify_client()

    try:
        # Get venues
        venues = get_active_venues(cur)

        # Scrape all venues
        raw_df = scrape_all_venues(venues)

        # Filter with validation configs
        filtered_df = filter_events(raw_df, venues)

        # Validate events
        validated_df = validate_events(filtered_df, sp)

        # Insert to database
        insert_to_database(validated_df, raw_df, filtered_df, cur, conn)

        print("\n" + "="*60)
        print("✅ SCRIPT COMPLETED SUCCESSFULLY")
        print("="*60 + "\n")

    except Exception as e:
        print(f"\n❌ Script failed with error: {e}")
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
