import pytest
from tests.test_auth import register_user, login
from app import db, User, Conversation, Message, Participant, socketio

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
    assert b'<span class="request-count-badge">1</span>' in response.data
    # The sender's name will not be in the main active list, but in the requests tab content
    # For now, we can just check that the request tab exists. A more robust test would parse the HTML.
    assert b'data-tab="requests"' in response.data

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
