/**
 * API Endpoint: POST /api/discover-venue
 * 
 * Discovers scraping configuration for a venue URL
 * Calls the FastAPI Python server for venue discovery
 */

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { url } = req.body;

  if (!url) {
    return res.status(400).json({ error: 'URL is required' });
  }

  // Validate URL
  try {
    new URL(url);
  } catch (e) {
    return res.status(400).json({ error: 'Invalid URL format' });
  }

  try {
    // Call the FastAPI Python server
    const apiUrl = process.env.VENUE_DISCOVERY_API_URL || 'http://localhost:8000';
    
    const response = await fetch(`${apiUrl}/discover`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ url }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      return res.status(response.status).json({
        error: errorData.error || 'Failed to discover venue',
        success: false
      });
    }

    const result = await response.json();
    
    if (!result.success) {
      return res.status(500).json({
        error: result.error || 'Discovery failed',
        success: false
      });
    }

    // Return config for user review
    res.status(200).json(result);
  } catch (error) {
    console.error('Error discovering venue:', error);
    res.status(500).json({ 
      error: 'Failed to connect to venue discovery service',
      message: error.message,
      success: false
    });
  }
}
