import pytest
from tests.test_auth import register_user, login
from app import db, User, Conversation, Message

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
    # The form action URL contains the conversation ID
    assert f'form method="POST"' in response.data.decode() # A bit of a hacky way to check we are on the right page
    assert Conversation.query.count() == 1 # Ensure no new convo was created

def test_send_and_view_message(client):
    """Test sending and viewing a message in a thread."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    login(client, 'user1', 'pw')

    # Start a chat
    client.get(f'/chat/start/{user2.id}')
    convo = Conversation.query.first()

    # Send a message
    response = client.post(f'/chat/{convo.id}', data={'body': 'Hello there!'}, follow_redirects=True)
    assert response.status_code == 200
    assert b'Hello there!' in response.data

    # Verify message is in the database
    message = Message.query.first()
    assert message is not None
    assert message.body == 'Hello there!'
    assert message.user_id == user1.id

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
