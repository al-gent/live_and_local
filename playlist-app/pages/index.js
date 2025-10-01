import React, { useState, useEffect } from 'react';

const App = () => {
  const [user, setUser] = useState(null);
  const [venues, setVenues] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [playlistCreated, setPlaylistCreated] = useState(null);
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [playlistName, setPlaylistName] = useState('🕺🏾live&local💃🏾');
  const [playlistDescription, setPlaylistDescription] = useState('upcoming shows at my favorite venues');
  const [songsPerArtist, setSongsPerArtist] = useState(3);
  const [daysAhead, setDaysAhead] = useState(21);
  const [selectedCity, setSelectedCity] = useState(null);
  const [playlists, setPlaylists] = useState([]);
  const [showPlaylists, setShowPlaylists] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState(null);

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

    const fetchPlaylists = async () => {
      try {
        const response = await fetch(`/api/user-playlists?spotify_user_id=${user.id}`);
        if (response.ok) {
          const data = await response.json();
          setPlaylists(data.playlists);
        }
      } catch (error) {
        console.error('Error fetching playlists:', error);
      }
    };

    if (user) {
      fetchVenues();
      fetchPlaylists();
    }
  }, [user]);

  const handleSpotifyLogin = () => {
    const state = Math.random().toString(36).substring(2, 15);
    sessionStorage.setItem('spotify_auth_state', state);
    
    const params = new URLSearchParams({
      client_id: process.env.NEXT_PUBLIC_SPOTIFY_CLIENT_ID,
      response_type: 'code',
      redirect_uri: process.env.NEXT_PUBLIC_REDIRECT_URI,
      scope: 'playlist-modify-public playlist-modify-private user-read-private user-read-email',
      state: state
    });
    
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
        
        setSelectedVenues([]);
        setPlaylistName('🕺🏾live&local💃🏾');
        setPlaylistDescription('upcoming shows at my favorite venues');
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
    setPlaylistName('🕺🏾live&local💃🏾');
    setPlaylistDescription('upcoming shows at my favorite venues');
    setSongsPerArtist(3);
  };

  const handleDeletePlaylist = async (playlistId) => {
    if (!confirm('Are you sure you want to delete this playlist?')) {
      return;
    }

    try {
      const response = await fetch('/api/delete-playlist', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          playlist_id: playlistId,
          spotify_user_id: user.id
        })
      });

      if (response.ok) {
        setPlaylists(playlists.filter(p => p.playlist_id !== playlistId));
      } else {
        alert('Failed to delete playlist');
      }
    } catch (error) {
      console.error('Error deleting playlist:', error);
      alert('Failed to delete playlist');
    }
  };

  const handleEditPlaylist = (playlist) => {
    setEditingPlaylist(playlist);
    setPlaylistName(playlist.playlist_name);
    setPlaylistDescription(playlist.playlist_description || '');
    setSelectedVenues(playlist.preferred_venues);
    setSongsPerArtist(playlist.songs_per_artist);
    setDaysAhead(playlist.days_ahead);
    setShowPlaylists(false);
  };

  const handleUpdatePlaylist = async () => {
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
      const response = await fetch('/api/update-playlist', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          playlist_id: editingPlaylist.playlist_id,
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
        alert('Playlist updated! It will refresh on the next scheduled update.');
        setEditingPlaylist(null);
        setSelectedVenues([]);
        setPlaylistName('🕺🏾live&local💃🏾');
        setPlaylistDescription('Upcoming shows at my favorite venues');
        setSongsPerArtist(3);
        setDaysAhead(21);
        
        // Refresh playlists
        const playlistsResponse = await fetch(`/api/user-playlists?spotify_user_id=${user.id}`);
        if (playlistsResponse.ok) {
          const data = await playlistsResponse.json();
          setPlaylists(data.playlists);
        }
      } else {
        alert(`Error: ${result.error}`);
      }
    } catch (error) {
      console.error('Error updating playlist:', error);
      alert('Failed to update playlist. Please try again.');
    } finally {
      setCreating(false);
    }
  };

  if (!user) {
    return (
      <div className="container">
        <div className="center">
          <h1>🕺🏾live&local💃🏾</h1>
          <p>turn your local concert calendar into a spotify playlist</p>
          <button onClick={handleSpotifyLogin} className="btn-primary">
            login with spotify
          </button>
        </div>
      </div>
    );
  }

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
          
          <p style={{color: '#b0b0b0', marginBottom: '30px'}}>
            Your playlist will be automatically updated every Sunday.<br/>
            Next update: <strong>{playlistCreated.next_update}</strong>
          </p>

          <button 
            onClick={() => {
              setPlaylistCreated(null);
              setShowPlaylists(false);
            }} 
            className="btn-primary"
          >
            Create Another Playlist
          </button>
        </div>
      </div>
    );
  }

  // My Playlists view
  if (showPlaylists) {
    return (
      <div className="container">
        <div className="header">
          <h1>🕺🏾live&local💃🏾</h1>
          <p>Your Playlists</p>
          <button onClick={() => setShowPlaylists(false)} className="back-btn">
            ← Back to create
          </button>
        </div>

        <h2>My Playlists ({playlists.length})</h2>
        {playlists.length === 0 ? (
          <p>You haven't created any playlists yet.</p>
        ) : (
          <div style={{display: 'flex', flexDirection: 'column', gap: '15px'}}>
            {playlists.map(playlist => (
              <div key={playlist.playlist_id} style={{
                padding: '20px',
                border: '2px solid #404040',
                borderRadius: '8px',
                background: '#1e1e1e'
              }}>
                <div style={{marginBottom: '10px'}}>
                  <strong style={{fontSize: '1.1em'}}>{playlist.playlist_name}</strong>
                </div>
                {playlist.playlist_description && (
                  <p style={{color: '#b0b0b0', fontSize: '0.9em', marginBottom: '10px'}}>
                    {playlist.playlist_description}
                  </p>
                )}
                <div style={{fontSize: '0.85em', color: '#b0b0b0'}}>
                  <div>{playlist.preferred_venues.length} venues • {playlist.songs_per_artist} songs per artist • {playlist.days_ahead} days ahead</div>
                  <div>Created: {new Date(playlist.created_at).toLocaleDateString()}</div>
                  {playlist.playlist_updated_at && (
                    <div>Last updated: {new Date(playlist.playlist_updated_at).toLocaleDateString()}</div>
                  )}
                </div>
                <div style={{marginTop: '15px', display: 'flex', gap: '10px'}}>
                  <a 
                    href={`https://open.spotify.com/playlist/${playlist.playlist_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn-secondary"
                  >
                    Open in Spotify
                  </a>
                  <button className="btn-secondary" onClick={() => handleEditPlaylist(playlist)}>Edit</button>
                  <button 
                    className="btn-secondary" 
                    style={{color: '#ff4444'}}
                    onClick={() => handleDeletePlaylist(playlist.playlist_id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="container">
      <div className="header">
        <h1>🕺🏾live&local💃🏾</h1>
        <p>Welcome, {user.display_name}</p>
        <p>
          you have {playlists.length} live&local playlist{playlists.length !== 1 ? 's' : ''}
        </p>
        <button onClick={() => setShowPlaylists(true)} className="back-btn" style={{color: '#1db954'}}>
          View playlists →
        </button>

      </div>

      <h2>{editingPlaylist ? 'edit playlist' : 'select venues'}</h2>
      {editingPlaylist && (
        <button onClick={() => {
          setEditingPlaylist(null);
          setSelectedVenues([]);
          setPlaylistName('🕺🏾live&local💃🏾');
          setPlaylistDescription('upcoming shows at my favorite venues');
          setSongsPerArtist(3);
          setDaysAhead(21);
        }} className="back-btn">
          ← Cancel editing
        </button>
      )}
      {loading ? (
        <p>Loading venues...</p>
      ) : (
        <>
          {!selectedCity ? (
            <div className="venues-grid">
              {Object.entries(
                venues.reduce((acc, venue) => {
                  const city = venue.city || 'Other';
                  if (!acc[city]) acc[city] = [];
                  acc[city].push(venue);
                  return acc;
                }, {})
              ).map(([city, cityVenues]) => (
                <div
                  key={city}
                  className="venue-card"
                  onClick={() => setSelectedCity(city)}
                >
                  <strong>{city}</strong>
                  <div style={{fontSize: '14px', color: '#b0b0b0', marginTop: '5px'}}>
                    {cityVenues.length} venue{cityVenues.length !== 1 ? 's' : ''}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <>
              <button onClick={() => setSelectedCity(null)} className="back-btn">
                ← Back to cities
              </button>
              <h3 style={{fontSize: '1.2em', marginBottom: '15px', color: '#f0f0f0'}}>{selectedCity}</h3>
              <div className="venues-grid">
                {venues
                  .filter(venue => (venue.city || 'Other') === selectedCity)
                  .map(venue => (
                    <div
                      key={venue.venue_id}
                      className={`venue-card ${selectedVenues.includes(venue.venue_id) ? 'selected' : ''}`}
                      onClick={() => handleVenueToggle(venue.venue_id)}
                    >
                      <strong>{venue.name}</strong>
                      {venue.address && <div style={{fontSize: '14px', color: '#b0b0b0'}}>{venue.address}</div>}
                    </div>
                  ))}
              </div>
            </>
          )}
        </>
      )}

      <div className="form-group">
        <label>playlist name</label>
        <input
          type="text"
          value={playlistName}
          onChange={(e) => setPlaylistName(e.target.value)}
          placeholder="My SF Shows"
        />
      </div>

      <div className="form-group">
        <label>description</label>
        <textarea
          value={playlistDescription}
          onChange={(e) => setPlaylistDescription(e.target.value)}
          placeholder="upcoming shows at my favorite venues"
          rows="3"
        />
      </div>

      <div className="form-group">
        <label>songs per artist</label>
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
        <label>time window (days)</label>
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
        onClick={editingPlaylist ? handleUpdatePlaylist : handleCreatePlaylist} 
        className="btn-primary"
        disabled={!playlistName.trim() || selectedVenues.length === 0 || creating}
      >
        {creating ? (editingPlaylist ? 'Updating...' : 'Creating Playlist...') : (editingPlaylist ? 'Update Playlist' : 'Create Playlist')}
      </button>
    </div>
  );
};

export default App;