import pytest
from datetime import date
from app import User, db

# --- Auth Test Helpers ---

def register_user(username='testuser', email='test@example.com', password='password'):
    """Helper to create and commit a user directly to the DB."""
    user = User(
        full_name=f'{username.capitalize()} User',
        username=username,
        email=email,
        date_of_birth=date(2000, 1, 1)
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user

def login(client, username, password):
    """Helper function to log in a user."""
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

def logout(client):
    """Helper function to log out a user."""
    return client.get('/logout', follow_redirects=True)

# --- Test Functions ---

def test_signup_page(client):
    """Test that the signup page loads and redirects correctly."""
    response = client.get('/signup')
    assert response.status_code == 302
    assert response.location == '/signup/1'

def test_successful_signup_creation(client):
    """
    Test that the user creation logic at the end of the signup flow works correctly.
    This test simulates the state of the session just before the final step.
    """
    with client.session_transaction() as sess:
        sess['signup_form'] = {
            'full_name': 'Test User',
            'email': 'test@example.com',
            'username': 'testuser',
            'password': 'password',
            'confirm_password': 'password'
        }

    # Now, submit the final step
    response = client.post('/signup/6', data={'date_of_birth': '2000-01-01'}, follow_redirects=True)

    assert b'Account created successfully! Please log in.' in response.data
    assert User.query.filter_by(username='testuser').count() == 1

def test_signup_duplicate_username(client):
    """Test that signing up with a duplicate username fails."""
    register_user(username='testuser')

    # Simulate session with data that would be valid up to step 3
    with client.session_transaction() as sess:
        sess['signup_form'] = {
            'full_name': 'Another User',
            'email': 'another@example.com'
        }

    response = client.post('/signup/3', data={'username': 'testuser'}, follow_redirects=True)

    assert b'Username is already taken.' in response.data

def test_login_and_logout(client):
    """Test that a registered user can log in and out."""
    register_user(username='loginuser', password='password')

    login_response = login(client, 'loginuser', 'password')
    # A robust check is to see if the logout link is present
    assert b'href="/logout"' in login_response.data

    logout_response = logout(client)
    assert b'You have been logged out.' in logout_response.data
    # After logout, the login form should be visible again
    assert b'Log In' in logout_response.data

def test_login_invalid_password(client):
    """Test logging in with an invalid password."""
    register_user(username='loginuser', password='password')
    response = login(client, 'loginuser', 'wrongpassword')
    assert b'Invalid username/email or password.' in response.data

def test_login_unregistered_user(client):
    """Test logging in with a username that does not exist."""
    response = login(client, 'nonexistentuser', 'password')
    assert b'Invalid username/email or password.' in response.data
