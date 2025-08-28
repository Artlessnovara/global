import pytest
from tests.test_auth import register_user, login
from app import db, User, Post, Comment, Notification

def test_add_comment_to_post(client):
    """Test that a user can add a comment to a post."""
    user = register_user(username='commenter', email='commenter@test.com', password='pw')
    post_author = register_user(username='author', email='author@test.com', password='pw')
    post = Post(author=post_author, content_type='text', text='A post to be commented on', mode='Test')
    db.session.add(post)
    db.session.commit()

    login(client, 'commenter', 'pw')

    response = client.post(f'/post/{post.id}/comment', data={
        'comment_text': 'This is a test comment.'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Your comment has been posted.' in response.data

    comment = Comment.query.first()
    assert comment is not None
    assert comment.text == 'This is a test comment.'
    assert comment.user_id == user.id
    assert comment.post_id == post.id

def test_view_comments_on_post(client):
    """Test that comments appear on the single post page."""
    user = register_user(username='commenter', email='commenter@test.com', password='pw')
    post_author = register_user(username='author', email='author@test.com', password='pw')
    post = Post(author=post_author, content_type='text', text='A post', mode='Test')
    db.session.add(post)
    db.session.commit() # Commit the post to give it an ID

    comment = Comment(text='A visible comment', author=user, post=post)

    db.session.add(comment)
    db.session.commit()

    login(client, 'commenter', 'pw')
    response = client.get(f'/post/{post.id}')

    assert response.status_code == 200
    assert b'A visible comment' in response.data
    assert b'commenter' in response.data

def test_comment_creates_notification(client):
    """Test that adding a comment creates a notification for the post author."""
    user = register_user(username='commenter', email='commenter@test.com', password='pw')
    post_author = register_user(username='author', email='author@test.com', password='pw')
    post = Post(author=post_author, content_type='text', text='A post', mode='Test')
    db.session.add(post)
    db.session.commit()

    login(client, 'commenter', 'pw')
    client.post(f'/post/{post.id}/comment', data={'comment_text': 'A new comment'})

    notification = Notification.query.filter_by(recipient_id=post_author.id).first()
    assert notification is not None
    assert notification.type == 'comment'
    assert notification.sender_id == user.id
    assert notification.related_id == post.id
