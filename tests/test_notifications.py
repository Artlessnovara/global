import pytest
from tests.test_auth import register_user, login, logout
from app import db, User, Post, Notification

def test_follow_creates_notification(client):
    """Test that following a user creates a notification."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    # user1 follows user2
    client.get(f'/follow/{user2.id}')

    notification = Notification.query.filter_by(recipient_id=user2.id).first()
    assert notification is not None
    assert notification.type == 'follow'
    assert notification.sender_id == user1.id

def test_like_creates_notification(client):
    """Test that liking a post creates a notification for the author."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    post = Post(author=user2, content_type='text', text='A post to be liked', mode='Test')
    db.session.add(post)
    db.session.commit()

    login(client, 'user1', 'pw')

    # user1 likes user2's post
    client.get(f'/react/{post.id}')

    notification = Notification.query.filter_by(recipient_id=user2.id).first()
    assert notification is not None
    assert notification.type == 'like'
    assert notification.sender_id == user1.id
    assert notification.related_id == post.id

def test_notification_page_and_filtering(client):
    """Test the notification page, its badge, and filtering logic."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    post_by_user1 = Post(author=user1, content_type='text', text='A post to be liked', mode='Test')
    db.session.add(post_by_user1)
    db.session.commit()

    # user2 follows user1 and likes their post
    login(client, 'user2', 'pw')
    client.get(f'/follow/{user1.id}')
    client.get(f'/react/{post_by_user1.id}')
    logout(client)

    # Log in as user1 and check for notifications
    login(client, 'user1', 'pw')
    home_response = client.get('/home')
    assert b'<span class="unread-badge">2</span>' in home_response.data

    # Check the "All" filter
    notifications_all = client.get('/notifications')
    assert b'started following you' in notifications_all.data
    assert b'liked your post' in notifications_all.data
    assert b'thumbnail-placeholder' in notifications_all.data # Check for thumbnail structure

    # After viewing "All", badge should be gone
    home_response_after_all = client.get('/home')
    assert b'unread-badge' not in home_response_after_all.data

    # Check the "Follows" filter
    notifications_follows = client.get('/notifications?filter=follow')
    assert b'started following you' in notifications_follows.data
    assert b'liked your post' not in notifications_follows.data

    # Check the "Likes" filter
    notifications_likes = client.get('/notifications?filter=like')
    assert b'started following you' not in notifications_likes.data
    assert b'liked your post' in notifications_likes.data
