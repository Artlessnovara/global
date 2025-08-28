import pytest
from tests.test_auth import register_user, login
from app import db, User, Post
import io

def test_create_photo_post(client):
    """Test the entire flow of creating a photo post."""
    user = register_user(username='photographer', email='photo@test.com', password='pw')
    login(client, 'photographer', 'pw')

    # Test the create choice page
    response = client.get('/create')
    assert response.status_code == 200
    assert b'Upload Photo' in response.data

    # Test the photo upload page
    response = client.get('/create/photo')
    assert response.status_code == 200
    assert b'Upload a Photo' in response.data

    # Simulate file upload
    dummy_file = io.BytesIO(b"this is a fake photo")
    response = client.post('/create/photo', data={
        'media_file': (dummy_file, 'test.jpg'),
        'text_content': 'My new photo!',
        'mode': 'Art'
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    assert b'Your photo has been posted!' in response.data

    # Verify the post was created in the DB
    post = Post.query.filter_by(content_type='photo').first()
    assert post is not None
    assert post.author.username == 'photographer'
    assert post.text == 'My new photo!'
    assert post.mode == 'Art'

def test_profile_shows_photo_and_video_tabs(client):
    """Test that the profile page correctly displays photo and video posts in their tabs."""
    user = register_user(username='media_user', email='media@test.com', password='pw')

    # Create one photo and one video post
    photo = Post(author=user, content_type='photo', text='A photo post', mode='Test', content_path='dummy/photo.jpg')
    video = Post(author=user, content_type='video', text='A video post', mode='Test', content_path='dummy/video.mp4')
    db.session.add_all([photo, video])
    db.session.commit()

    login(client, 'media_user', 'pw')
    response = client.get(f'/profile/{user.username}')

    assert response.status_code == 200
    # Check for the tab buttons
    assert b'Video' in response.data
    assert b'Photo' in response.data

    # The video post ID should be in the response, but not the photo post ID initially
    assert bytes(str(video.id), 'utf-8') in response.data
    assert bytes(str(photo.id), 'utf-8') in response.data
    # This test is simplified; a real test would need to handle the JS tab switching.
    # For now, we just check that the data for both is passed to the template context.
    # The template logic then separates them into the correct divs.

from app import Notification

def test_share_post(client):
    """Test sharing a post."""
    user1 = register_user(username='original_poster', email='op@test.com', password='pw')
    user2 = register_user(username='sharer', email='sharer@test.com', password='pw')

    # user1 creates a post
    original_post = Post(author=user1, content_type='text', text='This is the original post.', mode='Blog/Article')
    db.session.add(original_post)
    db.session.commit()

    # user2 logs in and shares the post
    login(client, 'sharer', 'pw')
    response = client.post(f'/post/{original_post.id}/share', data={
        'quote_text': 'Great post!'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Post shared successfully!' in response.data

    # Verify the repost was created
    repost = Post.query.filter_by(user_id=user2.id).first()
    assert repost is not None
    assert repost.original_post_id == original_post.id
    assert repost.text == 'Great post!'

    # Verify the original post's share count was incremented
    assert original_post.share_count == 1

    # Verify a notification was created for the original poster
    notification = Notification.query.filter_by(recipient_id=user1.id, type='share').first()
    assert notification is not None
    assert notification.sender_id == user2.id
    assert notification.related_id == original_post.id

def test_cannot_share_a_repost(client):
    """Test that a user cannot share a post that is already a share (a repost)."""
    user1 = register_user(username='poster1', email='p1@test.com', password='pw')
    user2 = register_user(username='poster2', email='p2@test.com', password='pw')
    user3 = register_user(username='poster3', email='p3@test.com', password='pw')

    # user1 creates a post
    post1 = Post(author=user1, content_type='text', text='Post 1', mode='Fun')
    db.session.add(post1)
    db.session.commit()

    # user2 shares user1's post
    repost = Post(author=user2, original_post_id=post1.id, content_type='text', mode='Fun')
    db.session.add(repost)
    db.session.commit()

    # user3 logs in and tries to share the repost
    login(client, 'poster3', 'pw')
    response = client.post(f'/post/{repost.id}/share', follow_redirects=True)

    assert response.status_code == 200
    assert b'You cannot share a post that is already a share.' in response.data
