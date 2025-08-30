import pytest
from tests.test_auth import register_user, login
from app import Post, User, db, Mode, Story
import io

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
    # After nav refactor, a better check is for the profile link.
    assert b'href="/profile/testuser"' in response.data

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

def test_create_story(client):
    """Test that a user can create a story."""
    register_user(username='storyteller', password='password')
    login(client, 'storyteller', 'password')

    # Create a dummy file in memory
    dummy_file = io.BytesIO(b"this is a fake image")

    response = client.post('/create_story', data={
        'story_file': (dummy_file, 'test.jpg')
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    assert b'Your story has been uploaded!' in response.data

    story = Story.query.first()
    assert story is not None
    assert story.author.username == 'storyteller'
    assert 'test.jpg' in story.media_path

def test_home_page_story_display(client):
    """Test that the home page only shows stories from followed users."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2_followed = register_user(username='user2', email='user2@test.com', password='pw')
    user3_unfollowed = register_user(username='user3', email='user3@test.com', password='pw')

    # user1 follows user2
    user1.follow(user2_followed)
    db.session.commit()

    # user2 and user3 create stories
    story_followed = Story(author=user2_followed, media_path='stories/followed.jpg')
    story_unfollowed = Story(author=user3_unfollowed, media_path='stories/unfollowed.jpg')
    db.session.add_all([story_followed, story_unfollowed])
    db.session.commit()

    login(client, 'user1', 'pw')
    response = client.get('/home')

    assert response.status_code == 200
    # The name of the followed user who posted a story should be visible
    assert bytes(user2_followed.full_name.split()[0], 'utf-8') in response.data
    # The name of the unfollowed user should not be visible
    assert bytes(user3_unfollowed.full_name.split()[0], 'utf-8') not in response.data

def test_story_viewer_loads(client):
    """Test that the story viewer page loads correctly."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    story = Story(author=user1, media_path='stories/test.jpg')
    db.session.add(story)
    db.session.commit()

    login(client, 'user1', 'pw')
    response = client.get(f'/story/{story.id}')

    assert response.status_code == 200
    assert bytes(user1.username, 'utf-8') in response.data
    assert b'stories/test.jpg' in response.data

def test_profile_page_new_layout(client):
    """Test the new profile page layout and that posts do not appear."""
    user = register_user(username='testprofile', password='password')
    login(client, 'testprofile', 'password')

    # Create a post that should NOT appear on the profile
    client.post('/create_post', data={
        'text_content': 'This post should not be on my profile.',
        'mode': 'Testing'
    })

    response = client.get(f'/profile/{user.username}')

    assert response.status_code == 200
    # Check for new layout classes
    assert b'new-profile-header' in response.data
    assert b'profile-stats-bar' in response.data
    # Check that post content is not there
    assert b'This post should not be on my profile.' not in response.data
    # Check that the new placeholders for empty media tabs are there
    assert b'No videos yet.' in response.data
    assert b'No photos yet.' in response.data

def test_profile_info_section(client):
    """Test that the new 'Intro' section on the profile displays correctly."""
    user = register_user(username='infouser', email='info@test.com', password='pw')
    user.bio = "This is a test bio."
    user.location = "Test City"
    user.work_education = "Test University"
    user.relationship_status = "Single"
    db.session.commit()

    login(client, 'infouser', 'pw')
    response = client.get(f'/profile/{user.username}')

    assert response.status_code == 200
    assert b'This is a test bio.' in response.data
    assert b'Lives in <strong>Test City</strong>' in response.data
    assert b'Works at <strong>Test University</strong>' in response.data
    assert b'<i class="fas fa-heart"></i> Single' in response.data
