#!/usr/bin/env python3
"""
FastAPI server for venue discovery
Run with: uvicorn venue_discovery_server:app --reload
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from meta_scraping_functions import discover_venue_scraping_config, format_for_database

app = FastAPI()

# Enable CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],  # Add your Next.js URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DiscoveryRequest(BaseModel):
    url: str

class DiscoveryResponse(BaseModel):
    success: bool
    config: dict = None
    sample_events: list = []
    error: str = None

@app.post("/discover", response_model=DiscoveryResponse)
async def discover_venue(request: DiscoveryRequest):
    """
    Discover scraping configuration for a venue URL
    """
    try:
        # Run the discovery
        result = discover_venue_scraping_config(request.url, use_selenium=True)
        
        if not result:
            return DiscoveryResponse(
                success=False,
                error="Failed to discover scraping configuration"
            )
        
        # Check if validation was successful
        if not result.get('validation_success', False):
            return DiscoveryResponse(
                success=False,
                error=f"Discovery found {result.get('num_events_found', 0)} events but failed validation. Date parse success: {result.get('date_parse_success_rate', 0):.0%}"
            )
        
        # Check if we found enough events to be meaningful
        num_events = result.get('num_events_found', 0)
        if num_events < 3:
            return DiscoveryResponse(
                success=False,
                error=f"Found only {num_events} event(s) - need at least 3 events to validate scraping configuration"
            )
        
        # Format for database
        config = format_for_database(result)
        
        # Return success with config and sample events
        return DiscoveryResponse(
            success=True,
            config=config,
            sample_events=result.get('events', [])[:5]  # First 5 events for review
        )
        
    except Exception as e:
        return DiscoveryResponse(
            success=False,
            error=str(e)
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("venue_discovery_server:app", host="0.0.0.0", port=8000, reload=True)
