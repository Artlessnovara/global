import pytest
from datetime import datetime, timezone
from tests.test_auth import register_user, login
from app import db, User, Conversation, Message, Participant, socketio, Story

def test_start_new_chat(client):
    """Test starting a new conversation."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    response = client.get(f'/chat/start/{user2.id}', follow_redirects=True)
    assert response.status_code == 200
    assert b'<span class="chat-header-name">User2 User</span>' in response.data

    convo = Conversation.query.first()
    assert convo is not None
    participant_users = [p.user for p in convo.participants]
    assert user1 in participant_users
    assert user2 in participant_users

def test_start_existing_chat(client):
    """Test that starting a chat with an existing conversation redirects properly."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')

    response = client.get(f'/chat/start/{user2.id}', follow_redirects=True)
    assert response.status_code == 200
    assert '<span class="chat-header-name">User2 User</span>' in response.data.decode()
    assert Conversation.query.count() == 1

def test_unauthorized_chat_access(client):
    """Test that a user cannot access a conversation they are not a part of."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    unauthorized_user = register_user(username='hacker', email='hacker@test.com', password='pw')

    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'hacker', 'pw')

    response = client.get(f'/chat/{convo.id}')
    assert response.status_code == 403

def test_send_and_receive_realtime_message(client, app):
    """Test sending and receiving a message in real-time via Socket.IO."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})
    socketio_client.emit('send_message', {'room': str(convo.id), 'message': 'Real-time hello!'})

    received = socketio_client.get_received()
    assert len(received) > 0
    assert received[0]['name'] == 'new_message'
    assert received[0]['args'][0]['body'] == 'Real-time hello!'

    message = Message.query.filter_by(body='Real-time hello!').first()
    assert message is not None
    assert message.conversation_id == convo.id

def test_message_request_flow(client):
    """Test the full message request workflow."""
    sender = register_user(username='sender', email='sender@test.com', password='pw')
    recipient = register_user(username='recipient', email='recipient@test.com', password='pw')

    # Sender starts a chat with Recipient (who does not follow Sender)
    login(client, 'sender', 'pw')
    client.get(f'/chat/start/{recipient.id}')

    convo = Conversation.query.first()
    assert convo is not None

    # Verify participant statuses
    sender_participant = Participant.query.filter_by(user_id=sender.id, conversation_id=convo.id).first()
    recipient_participant = Participant.query.filter_by(user_id=recipient.id, conversation_id=convo.id).first()
    assert sender_participant.status == 'active'
    assert recipient_participant.status == 'pending'

    # Log in as Recipient and check inbox
    login(client, 'recipient', 'pw')
    response = client.get('/chat')
    # Check for the new badge structure
    assert b'<span class="request-count-badge">1</span>' in response.data
    # The sender's name will still be in the document, inside the requests tab
    assert b'Sender User' in response.data

    # Recipient views the message thread and sees the request actions
    response = client.get(f'/chat/{convo.id}')
    # The message thread for a pending chat should show the actions
    assert b'Accept' in response.data
    assert b'Delete' in response.data
    assert b'Block' in response.data

    # Recipient accepts the chat
    response = client.get(f'/chat/accept/{convo.id}', follow_redirects=True)
    assert b'Chat request accepted.' in response.data

    # Verify participant status is now active by refreshing the object
    db.session.refresh(recipient_participant)
    assert recipient_participant.status == 'active'

    # Check that the chat is now in the main inbox, not requests
    response = client.get('/chat')
    assert b'Requests (' not in response.data # The "Requests" tab shouldn't show a count
    assert b'Sender User' in response.data

def test_pin_chat(client):
    """Test pinning and unpinning a chat."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')

    # Pin the chat
    client.post(f'/chat/pin/{convo.id}', follow_redirects=True)
    participant = Participant.query.filter_by(user_id=user1.id, conversation_id=convo.id).first()
    assert participant.is_pinned is True

    # Unpin the chat
    client.post(f'/chat/pin/{convo.id}', follow_redirects=True)
    db.session.refresh(participant)
    assert participant.is_pinned is False

def test_archive_chat(client):
    """Test archiving and unarchiving a chat."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')

    # Archive the chat
    client.post(f'/chat/archive/{convo.id}', follow_redirects=True)
    participant = Participant.query.filter_by(user_id=user1.id, conversation_id=convo.id).first()
    assert participant.is_archived is True

    # Unarchive the chat
    client.post(f'/chat/archive/{convo.id}', follow_redirects=True)
    db.session.refresh(participant)
    assert participant.is_archived is False

def test_archived_chat_not_in_inbox(client):
    """Test that an archived chat does not appear in the main inbox view."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    # Archive this conversation for user1
    p1 = Participant(user=user1, conversation=convo, is_archived=True)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')
    response = client.get('/chat')
    assert response.status_code == 200

    # We check the template context variable 'active_chats' passed to render_template
    # In a real test suite, you might capture the template context.
    # For this functional test, we check if the other user's name is absent from the active part of the page.
    # This is a bit brittle but works for now. We expect the active chats to be empty.
    assert b'No active chats yet.' in response.data

def test_pinned_chat_appears_first(client, app):
    """Test that pinned chats are sorted before unpinned chats."""
    from datetime import datetime, timedelta, timezone
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    user3 = register_user(username='user3', email='user3@test.com', password='pw')

    now = datetime.now(timezone.utc)

    # Convo 1 (unpinned, should be more recent but appear second)
    convo1 = Conversation(created_at=now - timedelta(minutes=10))
    p1a = Participant(user=user1, conversation=convo1)
    p1b = Participant(user=user2, conversation=convo1)
    msg1 = Message(conversation=convo1, sender=user2, body="Recent message", created_at=now)
    db.session.add_all([convo1, p1a, p1b, msg1])

    # Convo 2 (pinned, should be older but appear first)
    convo2 = Conversation(created_at=now - timedelta(minutes=20))
    p2a = Participant(user=user1, conversation=convo2, is_pinned=True)
    p2b = Participant(user=user3, conversation=convo2)
    msg2 = Message(conversation=convo2, sender=user3, body="Older message", created_at=now - timedelta(minutes=5))
    db.session.add_all([convo2, p2a, p2b, msg2])

    db.session.commit()

    login(client, 'user1', 'pw')
    response = client.get('/chat')
    assert response.status_code == 200

    data = response.data.decode()
    pos_pinned = data.find('User3 User')
    pos_unpinned = data.find('User2 User')

    assert pos_pinned != -1, "Pinned chat user's name not found in response"
    assert pos_unpinned != -1, "Unpinned chat user's name not found in response"
    assert pos_pinned < pos_unpinned, "Pinned chat did not appear before unpinned chat"

def test_disappearing_messages(client, app):
    """Test that disappearing messages are filtered correctly."""
    from datetime import timedelta
    import time

    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    # Create a group conversation
    convo = Conversation(is_group=True, name="Test Group")
    p1 = Participant(user=user1, conversation=convo, role='admin')
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')

    # Set a 1-second timer
    client.post(f'/chat/{convo.id}/settings/disappearing', data={'timer': 1})

    # Send a message
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})
    socketio_client.emit('send_message', {'room': str(convo.id), 'message': 'This will disappear'})

    # Give a moment for the message to be processed and saved
    time.sleep(0.1)

    # Verify the message exists initially
    response = client.get(f'/chat/{convo.id}')
    assert b'This will disappear' in response.data

    # Wait for the message to expire
    time.sleep(1)

    # Verify the message is gone
    response = client.get(f'/chat/{convo.id}')
    assert b'This will disappear' not in response.data

def test_story_indicator_in_chat_inbox(client, app):
    """Test that a story indicator appears for users with active stories."""
    from datetime import timedelta

    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    # user2 creates a story
    story = Story(author=user2, media_path='stories/test.jpg')
    db.session.add(story)

    # Create a conversation between them
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')
    response = client.get('/chat')
    assert response.status_code == 200

    # Check for the 'has-story' class on the container of user2's avatar
    expected_html_div = f'<div class="chat-avatar-container has-story">'
    assert expected_html_div in response.data.decode()

    # Check that the link around the avatar points to the correct story route
    expected_link = f'<a href="/stories/user/{user2.id}">'
    assert expected_link in response.data.decode()

    # Test the redirection
    response = client.get(f'/stories/user/{user2.id}', follow_redirects=False)
    assert response.status_code == 302
    assert response.location == f'/story/{story.id}'

    # Test that an expired story does not show the indicator
    story.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db.session.commit()
    response = client.get('/chat')
    assert expected_html_div not in response.data.decode()
