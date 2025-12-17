#!/usr/bin/env python3
"""
Standalone API bridge for venue discovery
Can be called from Node.js/Next.js
"""
import sys
import json
import os
from meta_scraping_functions import discover_venue_scraping_config, format_for_database

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "URL required"}))
        sys.exit(1)
    
    url = sys.argv[1]
    
    try:
        # Discover the scraping configuration
        result = discover_venue_scraping_config(url, use_selenium=True)
        
        if not result:
            print(json.dumps({"error": "Failed to discover configuration"}))
            sys.exit(1)
        
        # Format for database
        config = format_for_database(result)
        
        # Return both the config and sample events
        output = {
            "success": True,
            "config": config,
            "sample_events": result.get('events', [])[:5]  # Show first 5 events
        }
        
        print(json.dumps(output))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
