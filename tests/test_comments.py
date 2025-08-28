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

def test_add_reply_to_comment(client):
    """Test that a user can reply to an existing comment."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    post = Post(author=user1, content_type='text', text='A post', mode='Test')
    comment = Comment(text='Parent comment', author=user1, post=post)
    db.session.add_all([post, comment])
    db.session.commit()

    login(client, 'user2', 'pw')
    client.post(f'/post/{post.id}/comment', data={
        'comment_text': 'This is a reply.',
        'parent_id': comment.id
    }, follow_redirects=True)

    reply = Comment.query.filter_by(text='This is a reply.').first()
    assert reply is not None
    assert reply.parent_id == comment.id
    assert reply.author == user2

def test_delete_comment(client):
    """Test that a user can delete their own comment."""
    user = register_user()
    post = Post(author=user, content_type='text', text='A post', mode='Test')
    comment = Comment(text='To be deleted', author=user, post=post)
    db.session.add_all([post, comment])
    db.session.commit()

    login(client, user.username, 'password')
    response = client.post(f'/comment/{comment.id}/delete')

    assert response.status_code == 200
    assert response.json['status'] == 'success'
    assert Comment.query.get(comment.id) is None

def test_delete_comment_with_replies(client):
    """Test that deleting a comment also deletes its replies."""
    user = register_user()
    post = Post(author=user, content_type='text', text='A post', mode='Test')
    parent_comment = Comment(text='Parent', author=user, post=post)
    db.session.add_all([post, parent_comment])
    db.session.commit()

    reply_comment = Comment(text='Reply', author=user, post=post, parent_id=parent_comment.id)
    db.session.add(reply_comment)
    db.session.commit()

    assert Comment.query.count() == 2

    login(client, user.username, 'password')
    client.post(f'/comment/{parent_comment.id}/delete')

    assert Comment.query.count() == 0

def test_edit_comment(client):
    """Test that a user can edit their own comment."""
    user = register_user()
    post = Post(author=user, content_type='text', text='A post', mode='Test')
    comment = Comment(text='Original text', author=user, post=post)
    db.session.add_all([post, comment])
    db.session.commit()

    login(client, user.username, 'password')
    response = client.post(f'/comment/{comment.id}/edit', data={'text': 'Edited text'})

    assert response.status_code == 200
    assert response.json['status'] == 'success'
    db.session.refresh(comment)
    assert comment.text == 'Edited text'

def test_react_to_comment(client):
    """Test reacting to a comment."""
    user = register_user()
    post = Post(author=user, content_type='text', text='A post', mode='Test')
    comment = Comment(text='A comment to react to', author=user, post=post)
    db.session.add_all([post, comment])
    db.session.commit()

    login(client, user.username, 'password')

    # Add a reaction
    response = client.post(f'/comment/{comment.id}/react', json={'emoji': '❤️'})
    assert response.status_code == 201
    assert response.json['status'] == 'added'
    assert response.json['count'] == 1

    # Remove the reaction
    response = client.post(f'/comment/{comment.id}/react', json={'emoji': '❤️'})
    assert response.status_code == 200
    assert response.json['status'] == 'removed'
    assert response.json['count'] == 0
