import React, { useState, useEffect } from 'react';

const App = () => {
  const [user, setUser] = useState(null);
  const [venues, setVenues] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [playlistCreated, setPlaylistCreated] = useState(null);
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [playlistName, setPlaylistName] = useState('Live & Local');
  const [playlistDescription, setPlaylistDescription] = useState('Upcoming shows at my favorite venues');
  const [songsPerArtist, setSongsPerArtist] = useState(3);
  const [daysAhead, setDaysAhead] = useState(21);

  // Check for user data from OAuth callback
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const userData = urlParams.get('user');
    const error = urlParams.get('error');
    
    if (error) {
      alert(`Login failed: ${error}`);
      return;
    }
    
    if (userData) {
      try {
        const user = JSON.parse(decodeURIComponent(userData));
        setUser(user);
        // Clean up URL
        window.history.replaceState({}, document.title, '/');
      } catch (err) {
        console.error('Failed to parse user data:', err);
      }
    }
  }, []);

  // Fetch venues from API
  useEffect(() => {
    const fetchVenues = async () => {
      setLoading(true);
      try {
        const response = await fetch('/api/venues');
        if (!response.ok) {
          throw new Error('Failed to fetch venues');
        }
        const venuesData = await response.json();
        setVenues(venuesData);
      } catch (error) {
        console.error('Error fetching venues:', error);
        alert('Failed to load venues. Please refresh the page.');
      } finally {
        setLoading(false);
      }
    };

    if (user) {
      fetchVenues();
    }
  }, [user]);

  const handleSpotifyLogin = () => {
    // Generate a random state parameter for security
    const state = Math.random().toString(36).substring(2, 15);
    
    // Store state in sessionStorage to verify later
    sessionStorage.setItem('spotify_auth_state', state);
    
    // Spotify OAuth parameters
    const params = new URLSearchParams({
      client_id: process.env.NEXT_PUBLIC_SPOTIFY_CLIENT_ID,
      response_type: 'code',
      redirect_uri: process.env.NEXT_PUBLIC_REDIRECT_URI,
      scope: 'playlist-modify-public playlist-modify-private user-read-private user-read-email',
      state: state
    });
    
    // Redirect to Spotify authorization page
    window.location.href = `https://accounts.spotify.com/authorize?${params.toString()}`;
  };

  const handleVenueToggle = (venueId) => {
    setSelectedVenues(prev => 
      prev.includes(venueId) 
        ? prev.filter(id => id !== venueId)
        : [...prev, venueId]
    );
  };

  const handleCreatePlaylist = async () => {
    if (!playlistName.trim()) {
      alert('Please enter a playlist name');
      return;
    }
    
    if (selectedVenues.length === 0) {
      alert('Please select at least one venue');
      return;
    }

    setCreating(true);

    try {
      const response = await fetch('/api/create-playlist', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          spotify_user_id: user.id,
          playlist_name: playlistName,
          playlist_description: playlistDescription,
          preferred_venues: selectedVenues,
          songs_per_artist: songsPerArtist,
          days_ahead: daysAhead
        })
      });

      const result = await response.json();

      if (response.ok) {
        // Calculate next Sunday
        const today = new Date();
        const nextSunday = new Date(today);
        nextSunday.setDate(today.getDate() + ((7 - today.getDay()) % 7 || 7));
        const nextSundayFormatted = nextSunday.toLocaleDateString('en-US', { 
          weekday: 'long', 
          month: 'long', 
          day: 'numeric' 
        });

        setPlaylistCreated({
          tracks_added: result.tracks_added,
          artists_found: result.artists_found,
          venue_count: selectedVenues.length,
          next_update: nextSundayFormatted
        });
        
        // Reset form
        setSelectedVenues([]);
        setPlaylistName('Live & Local');
        setPlaylistDescription('Upcoming shows at my favorite venues');
        setSongsPerArtist(3);
        setDaysAhead(21);
      } else {
        alert(`Error: ${result.error}`);
      }
    } catch (error) {
      console.error('Error creating playlist:', error);
      alert('Failed to create playlist. Please try again.');
    } finally {
      setCreating(false);
    }
  };

  const handleLogout = () => {
    setUser(null);
    setVenues([]);
    setSelectedVenues([]);
    setPlaylistName('Live & Local');
    setPlaylistDescription('Upcoming shows at my favorite venues');
    setSongsPerArtist(3);
  };

  // Login screen
  if (!user) {
    return (
      <div className="container">
        <div className="center">
          <h1>Live & Local</h1>
          <p>Create playlists from upcoming SF shows</p>
          <button onClick={handleSpotifyLogin} className="btn-primary">
            Login with Spotify
          </button>
        </div>
      </div>
    );
  }

  // Success screen after playlist creation
  if (playlistCreated) {
    return (
      <div className="container">
        <div className="center">
          <h1>Playlist Created!</h1>
          <p style={{fontSize: '1.2em', marginBottom: '40px'}}>
            Your playlist has been successfully created with<br/>
            <strong>{playlistCreated.tracks_added} songs</strong> from <strong>{playlistCreated.artists_found} artists</strong><br/>
            across <strong>{playlistCreated.venue_count} venue{playlistCreated.venue_count !== 1 ? 's' : ''}</strong>
          </p>
          
          <p style={{color: '#666', marginBottom: '30px'}}>
            Your playlist will be automatically updated every Sunday.<br/>
            Next update: <strong>{playlistCreated.next_update}</strong>
          </p>

          <button 
            onClick={() => {
              setPlaylistCreated(null);
            }} 
            className="btn-primary"
          >
            Create Another Playlist
          </button>
        </div>
      </div>
    );
  }

  // Main app screen
  return (
    <div className="container">
      <div className="header">
        <h1>Live & Local</h1>
        <p>Welcome, {user.display_name}</p>
        <button onClick={handleLogout} className="back-btn">
          Logout
        </button>
      </div>

      <h2>Select Venues</h2>
      {loading ? (
        <p>Loading venues...</p>
      ) : (
        <>
          {Object.entries(
            venues.reduce((acc, venue) => {
              const city = venue.city || 'Other';
              if (!acc[city]) acc[city] = [];
              acc[city].push(venue);
              return acc;
            }, {})
          ).map(([city, cityVenues]) => (
            <div key={city} style={{marginBottom: '30px'}}>
              <h3 style={{fontSize: '1.2em', marginBottom: '15px', color: '#666'}}>{city}</h3>
              <div className="venues-grid">
                {cityVenues.map(venue => (
                  <div
                    key={venue.venue_id}
                    className={`venue-card ${selectedVenues.includes(venue.venue_id) ? 'selected' : ''}`}
                    onClick={() => handleVenueToggle(venue.venue_id)}
                  >
                    <strong>{venue.name}</strong>
                    {venue.address && <div style={{fontSize: '14px', color: '#666'}}>{venue.address}</div>}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </>
      )}

      <div className="form-group">
        <label>Playlist Name</label>
        <input
          type="text"
          value={playlistName}
          onChange={(e) => setPlaylistName(e.target.value)}
          placeholder="My SF Shows"
        />
      </div>

      <div className="form-group">
        <label>Description (optional)</label>
        <textarea
          value={playlistDescription}
          onChange={(e) => setPlaylistDescription(e.target.value)}
          placeholder="Upcoming shows at my favorite venues"
          rows="3"
        />
      </div>

      <div className="form-group">
        <label>Songs per artist</label>
        <input
          type="number"
          className="number-input"
          value={songsPerArtist}
          onChange={(e) => setSongsPerArtist(parseInt(e.target.value))}
          min="1"
          max="10"
        />
      </div>

      <div className="form-group">
        <label>Days ahead (how far into the future to look for shows)</label>
        <input
          type="number"
          className="number-input"
          value={daysAhead}
          onChange={(e) => setDaysAhead(parseInt(e.target.value))}
          min="1"
          max="90"
        />
      </div>

      <button 
        onClick={handleCreatePlaylist} 
        className="btn-primary"
        disabled={!playlistName.trim() || selectedVenues.length === 0 || creating}
      >
        {creating ? 'Creating Playlist...' : 'Create Playlist'}
      </button>
    </div>
  );
};

export default App;