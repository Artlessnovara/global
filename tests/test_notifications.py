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

def test_notification_interactions(client):
    """Test notification links, badge counts, and mark-as-read functionality."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    post_by_user1 = Post(author=user1, content_type='text', text='A post to be liked', mode='Test')
    db.session.add(post_by_user1)
    db.session.commit()

    # user2 follows user1 and likes their post, creating two notifications for user1
    login(client, 'user2', 'pw')
    client.get(f'/follow/{user1.id}')
    client.get(f'/react/{post_by_user1.id}')
    logout(client)

    # Log in as user1, should have 2 unread notifications
    login(client, 'user1', 'pw')
    home_response = client.get('/home')
    assert b'<span class="unread-badge">2</span>' in home_response.data

    # Get the notifications from the DB to check their properties
    notifs = Notification.query.filter_by(recipient_id=user1.id).order_by(Notification.type).all()
    assert len(notifs) == 2
    follow_notif = notifs[0]
    like_notif = notifs[1]
    assert follow_notif.is_read == False
    assert like_notif.is_read == False

    # Check that the notification page contains the correct links
    notifications_page = client.get('/notifications')
    assert f'href="/profile/{user2.username}"' in notifications_page.data.decode()
    assert f'href="/post/{post_by_user1.id}"' in notifications_page.data.decode()

    # Simulate clicking the 'like' notification to mark it as read
    client.post(f'/notifications/read/{like_notif.id}')

    # Badge count should now be 1
    home_response_after_click = client.get('/home')
    assert b'<span class="unread-badge">1</span>' in home_response_after_click.data

    # Verify in the DB
    db.session.refresh(like_notif)
    assert like_notif.is_read == True
    db.session.refresh(follow_notif)
    assert follow_notif.is_read == False

    # Check the "Follows" filter
    notifications_follows = client.get('/notifications?filter=follow')
    assert b'started following you' in notifications_follows.data
    assert b'liked your post' not in notifications_follows.data

    # Check the "Likes" filter
    notifications_likes = client.get('/notifications?filter=like')
    assert b'started following you' not in notifications_likes.data
    assert b'liked your post' in notifications_likes.data

def test_post_detail_page_loads(client):
    """Test that the single post detail page loads correctly."""
    user = register_user(username='testuser', email='test@test.com', password='pw')
    post = Post(author=user, content_type='text', text='A post to be viewed', mode='Test')
    db.session.add(post)
    db.session.commit()

    login(client, 'testuser', 'pw')

    response = client.get(f'/post/{post.id}')
    assert response.status_code == 200
    assert b'A post to be viewed' in response.data

def test_close_friends_notifications(client):
    """Test close friends functionality and priority notification highlighting."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    # user1 adds user2 as a close friend
    login(client, 'user1', 'pw')
    client.get(f'/add_close_friend/{user2.id}')
    assert user1.is_close_friend(user2)
    logout(client)

    # user2 follows user1, creating a notification
    login(client, 'user2', 'pw')
    client.get(f'/follow/{user1.id}')
    logout(client)

    # Log in as user1 and check that the notification is highlighted
    login(client, 'user1', 'pw')
    response = client.get('/notifications')
    assert b'notification-priority' in response.data

def test_achievement_notification(client):
    """Test that an achievement notification is created at a milestone."""
    # Create 9 follower users
    for i in range(9):
        register_user(username=f'follower{i}', email=f'f{i}@test.com', password='pw')

    main_user = register_user(username='mainuser', email='main@test.com', password='pw')

    # Have the 9 users follow main_user
    for i in range(9):
        login(client, f'follower{i}', 'pw')
        client.get(f'/follow/{main_user.id}')
        logout(client)

    # The 10th follower triggers the achievement
    tenth_follower = register_user(username='follower10', email='f10@test.com', password='pw')
    login(client, 'follower10', 'pw')
    client.get(f'/follow/{main_user.id}')

    # Check for the achievement notification
    notification = Notification.query.filter_by(recipient_id=main_user.id, type='achievement').first()
    assert notification is not None
    assert notification.related_id == 10
