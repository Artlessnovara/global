import pytest
from tests.test_auth import register_user, login
from app import Post, User, db, Mode

def test_loading_page(client):
    """Test that the loading page is the first page seen."""
    response = client.get('/')
    assert response.status_code == 200
    assert b'GLOOBA' in response.data
    assert b'Join the world in every mood.' in response.data

def test_home_page_requires_login(client):
    """Test that the home page redirects to login if user is not authenticated."""
    response = client.get('/home', follow_redirects=True)
    assert b'Log In' in response.data
    assert b'Email, or username' in response.data

def test_home_page_loads_for_logged_in_user(client):
    """Test that the home page loads correctly for a logged-in user."""
    register_user(username='testuser', password='password')
    login(client, 'testuser', 'password')

    response = client.get('/home')
    assert response.status_code == 200
    assert b'href="/logout"' in response.data

def test_create_and_view_post(client):
    """Test that a user can create a post and it appears on the home page."""
    register_user(username='postuser', password='password')
    login(client, 'postuser', 'password')

    home_response_before = client.get('/home')
    assert b'This is my first post!' not in home_response_before.data

    create_post_response = client.post('/create_post', data={
        'text_content': 'This is my first post!',
        'mode': 'Testing'
    }, follow_redirects=True)

    assert b'Your post has been created!' in create_post_response.data

    post = Post.query.filter_by(mode='Testing').first()
    assert post is not None
    assert post.text == 'This is my first post!'

    home_response_after = client.get('/home')
    assert b'This is my first post!' in home_response_after.data
    assert b'@Testing' in home_response_after.data
    assert b'Postuser User' in home_response_after.data

def test_settings_page(client, seed_db):
    """Test that a user can view and update their settings."""
    register_user(username='settingsuser', password='password')
    login(client, 'settingsuser', 'password')

    response = client.get('/settings')
    assert response.status_code == 200
    assert b'Mode Preferences' in response.data

    music_mode = Mode.query.filter_by(name='Music').first()
    gaming_mode = Mode.query.filter_by(name='Gaming').first()
    response = client.post('/settings', data={
        'modes': [str(music_mode.id), str(gaming_mode.id)]
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Your preferences have been updated.' in response.data

    user = User.query.filter_by(username='settingsuser').first()
    preferred_mode_names = [mode.name for mode in user.preferred_modes]
    assert 'Music' in preferred_mode_names
    assert 'Gaming' in preferred_mode_names

def test_suggestions_page(client, seed_db):
    """Test the suggestion logic."""
    main_user = register_user(username='mainuser', password='password')
    music_user = register_user(username='musicuser', email='music@test.com')
    sports_user = register_user(username='sportsuser', email='sports@test.com')

    music_post = Post(user_id=music_user.id, content_type='text', text='A music post', mode='Music')
    sports_post = Post(user_id=sports_user.id, content_type='text', text='A sports post', mode='Sports')
    db.session.add_all([music_post, sports_post])
    db.session.commit()

    login(client, 'mainuser', 'password')

    music_mode = Mode.query.filter_by(name='Music').first()
    client.post('/settings', data={'modes': [str(music_mode.id)]})

    response = client.get('/suggestions')
    assert response.status_code == 200
    assert b'@musicuser' in response.data
    assert b'@sportsuser' not in response.data

def test_more_page(client):
    """Test that the 'More' page loads and contains a link to settings."""
    register_user(username='testuser', password='password')
    login(client, 'testuser', 'password')

    response = client.get('/more')
    assert response.status_code == 200
    assert b'More Options' in response.data
    assert b'href="/settings"' in response.data

def test_my_modes_page(client, seed_db):
    """Test that the 'My Modes' page loads correctly."""
    register_user(username='testuser', password='password')
    login(client, 'testuser', 'password')

    artist_mode = Mode.query.filter_by(name='Artist').first()
    business_mode = Mode.query.filter_by(name='Business/Marketplace').first()
    client.post('/settings', data={'modes': [str(artist_mode.id), str(business_mode.id)]})

    response = client.get('/modes/my')
    assert response.status_code == 200
    assert b'My Modes' in response.data
    assert b'Artist' in response.data
    assert b'Business/Marketplace' in response.data
    assert b'Education' not in response.data

def test_discover_modes_page(client, seed_db):
    """Test that the 'Discover Modes' page loads and shows all modes."""
    register_user(username='testuser', password='password')
    login(client, 'testuser', 'password')

    response = client.get('/modes/discover')
    assert response.status_code == 200
    assert b'Discover Modes' in response.data
    assert b'Education' in response.data
    assert b'Networking' in response.data
    assert b'Fun' in response.data
