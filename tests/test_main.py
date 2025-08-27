import pytest
from tests.test_auth import register_user, login
from app import Post

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
    # A robust check is to see if the logout link is present
    assert b'href="/logout"' in response.data

def test_create_and_view_post(client):
    """Test that a user can create a post and it appears on the home page."""
    # Sign up and log in
    register_user(username='postuser', password='password')
    login(client, 'postuser', 'password')

    # Check home page before posting
    home_response_before = client.get('/home')
    assert b'This is my first post!' not in home_response_before.data

    # Create a new post
    create_post_response = client.post('/create_post', data={
        'text_content': 'This is my first post!',
        'mode': 'Testing'
    }, follow_redirects=True)

    assert b'Your post has been created!' in create_post_response.data

    # Check that the post is in the database
    post = Post.query.filter_by(mode='Testing').first()
    assert post is not None
    assert post.text == 'This is my first post!'

    # Check that the post appears on the home page
    home_response_after = client.get('/home')
    assert b'This is my first post!' in home_response_after.data
    assert b'@Testing' in home_response_after.data
    # Check for the author's full name: 'Postuser User'
    assert b'Postuser User' in home_response_after.data
