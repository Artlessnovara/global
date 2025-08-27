import pytest
from tests.test_auth import register_user, login
from app import db, User, Conversation, Message, socketio

def test_start_new_chat(client):
    """Test starting a new conversation."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    # Start a chat with user2
    response = client.get(f'/chat/start/{user2.id}', follow_redirects=True)
    assert response.status_code == 200
    assert b'Chat with User2 User' in response.data

    # Verify conversation was created with correct participants
    convo = Conversation.query.first()
    assert convo is not None
    assert user1 in convo.participants
    assert user2 in convo.participants

def test_start_existing_chat(client):
    """Test that starting a chat with an existing conversation redirects properly."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    # Manually create a conversation
    convo = Conversation()
    convo.participants.append(user1)
    convo.participants.append(user2)
    db.session.add(convo)
    db.session.commit()

    login(client, 'user1', 'pw')

    # Attempt to start a chat again
    response = client.get(f'/chat/start/{user2.id}', follow_redirects=True)
    assert response.status_code == 200

    # Check that it redirected to the existing conversation thread
    assert f'Chat with User2 User' in response.data.decode()
    assert Conversation.query.count() == 1 # Ensure no new convo was created

def test_unauthorized_chat_access(client):
    """Test that a user cannot access a conversation they are not a part of."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    unauthorized_user = register_user(username='hacker', email='hacker@test.com', password='pw')

    # Create a conversation between user1 and user2
    convo = Conversation()
    convo.participants.append(user1)
    convo.participants.append(user2)
    db.session.add(convo)
    db.session.commit()

    # Log in as the unauthorized user
    login(client, 'hacker', 'pw')

    # Attempt to access the conversation
    response = client.get(f'/chat/{convo.id}')
    assert response.status_code == 403 # Forbidden

def test_send_and_receive_realtime_message(client, app):
    """Test sending and receiving a message in real-time via Socket.IO."""
    # Create users and conversation directly
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    convo.participants.append(user1)
    convo.participants.append(user2)
    db.session.add(convo)
    db.session.commit()

    # Log in user1 using the standard client to establish a session
    login(client, 'user1', 'pw')

    # Create a socketio client that uses the authenticated flask client
    socketio_client = socketio.test_client(app, flask_test_client=client)

    # Join the room
    socketio_client.emit('join', {'room': str(convo.id)})

    # Emit a message
    socketio_client.emit('send_message', {'room': str(convo.id), 'message': 'Real-time hello!'})

    # Check for the broadcasted message
    received = socketio_client.get_received()
    assert len(received) > 0
    assert received[0]['name'] == 'new_message'
    assert received[0]['args'][0]['body'] == 'Real-time hello!'

    # Verify the message was saved to the database
    message = Message.query.filter_by(body='Real-time hello!').first()
    assert message is not None
    assert message.conversation_id == convo.id
