import pytest
from tests.test_auth import register_user, login
from app import db, User, Conversation, Message, Participant, socketio

def test_create_public_room(client):
    """Test creating a new public room."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    login(client, 'user1', 'pw')

    response = client.post('/rooms/create', data={
        'name': 'Test Room',
        'description': 'A room for testing.'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Test Room' in response.data

    room = Conversation.query.filter_by(name='Test Room').first()
    assert room is not None
    assert room.is_public is True

    host = Participant.query.filter_by(user_id=user1.id, conversation_id=room.id).first()
    assert host is not None
    assert host.role == 'host'

def test_discover_public_rooms(client):
    """Test that public rooms appear on the discover page."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    login(client, 'user1', 'pw')

    # Create a public room
    client.post('/rooms/create', data={'name': 'Visible Room'}, follow_redirects=True)

    # Create a private group (should not be visible)
    private_group = Conversation(name='Private Group', is_group=True, is_public=False)
    db.session.add(private_group)
    db.session.commit()

    response = client.get('/rooms/discover')
    assert response.status_code == 200
    assert b'Visible Room' in response.data
    assert b'Private Group' not in response.data

def test_join_room_and_send_message(client, app):
    """Test joining a room and sending a message."""
    host = register_user(username='host', email='host@test.com', password='pw')
    joiner = register_user(username='joiner', email='joiner@test.com', password='pw')

    # Host creates a room
    login(client, 'host', 'pw')
    client.post('/rooms/create', data={'name': 'Fun Room'}, follow_redirects=True)
    room = Conversation.query.filter_by(name='Fun Room').first()

    # New user joins the room
    login(client, 'joiner', 'pw')
    client.post(f'/rooms/join/{room.id}', follow_redirects=True)

    joiner_participant = Participant.query.filter_by(user_id=joiner.id, conversation_id=room.id).first()
    assert joiner_participant is not None
    # The default role upon joining should be 'listener' as per the route logic
    assert joiner_participant.role == 'listener'

    # For this test, let's manually upgrade the user to a 'participant' to test sending messages
    joiner_participant.role = 'participant'
    db.session.commit()

    # Joiner sends a message
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(room.id)})
    socketio_client.emit('send_message', {'room': str(room.id), 'message': 'Hello from joiner!'})

    message = Message.query.filter_by(body='Hello from joiner!').first()
    assert message is not None
    assert message.conversation_id == room.id
    assert message.user_id == joiner.id

def test_listener_cannot_send_message(client):
    """Test that a user with the 'listener' role cannot send messages."""
    host = register_user(username='host', email='host@test.com', password='pw')
    listener = register_user(username='listener', email='listener@test.com', password='pw')

    login(client, 'host', 'pw')
    client.post('/rooms/create', data={'name': 'Listen Only Room'}, follow_redirects=True)
    room = Conversation.query.filter_by(name='Listen Only Room').first()

    login(client, 'listener', 'pw')
    client.post(f'/rooms/join/{room.id}')

    # The view should indicate they are a listener
    response = client.get(f'/rooms/{room.id}')
    assert b'You are a listener' in response.data
    assert b'Type a message...' not in response.data
