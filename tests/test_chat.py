import pytest
import io
from tests.test_auth import register_user, login, logout
from app import db, User, Conversation, Message, Participant, socketio, Post

def test_start_new_chat(client):
    """Test starting a new conversation."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    response = client.get(f'/chat/start/{user2.id}', follow_redirects=True)
    assert response.status_code == 200
    assert b'Chat with User2 User' in response.data

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
    assert f'Chat with User2 User' in response.data.decode()
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
    logout(client) # Ensure session is clean before logging in as new user
    login(client, 'recipient', 'pw')
    response = client.get('/chat')
    assert b'Requests (1)' in response.data
    assert b'Sender User' in response.data # Check for full name, not username

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

def test_send_and_receive_reply_message(client, app):
    """Test sending a message that is a reply to another message."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    parent_message = Message(conversation=convo, sender=user1, body="This is the message to be replied to.")
    db.session.add_all([convo, p1, p2, parent_message])
    db.session.commit()

    # User 2 replies to User 1's message
    login(client, 'user2', 'pw')
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})
    socketio_client.emit('send_message', {
        'room': str(convo.id),
        'message': 'This is a reply.',
        'parent_id': parent_message.id
    })

    # Check the socket response
    received = socketio_client.get_received()
    assert received[0]['name'] == 'new_message'
    reply_data = received[0]['args'][0]
    assert reply_data['body'] == 'This is a reply.'
    assert reply_data['parent'] is not None
    assert reply_data['parent']['body'] == parent_message.body
    assert reply_data['parent']['author_name'] == user1.full_name

    # Check the database
    reply_message = Message.query.filter_by(body='This is a reply.').first()
    assert reply_message is not None
    assert reply_message.parent_id == parent_message.id

    # Check the rendered HTML
    response = client.get(f'/chat/{convo.id}')
    assert response.status_code == 200
    assert b'parent-message-preview' in response.data
    assert bytes(parent_message.body, 'utf-8') in response.data
    assert bytes(user1.full_name, 'utf-8') in response.data

def test_send_media_message(client, app):
    """Test uploading a media file and sending it as a message."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'user1', 'pw')

    # 1. Upload the media file
    dummy_file = io.BytesIO(b"this is a fake image")
    response = client.post(f'/chat/conversation/{convo.id}/upload_media', data={
        'media_file': (dummy_file, 'test.jpg'),
    }, content_type='multipart/form-data')

    assert response.status_code == 200
    upload_data = response.json
    assert upload_data['success'] == True
    assert 'content_path' in upload_data

    # 2. Send the message via socket
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})
    socketio_client.emit('send_message', {
        'room': str(convo.id),
        'message': 'Check out this pic!',
        'content_type': upload_data['content_type'],
        'content_path': upload_data['content_path']
    })

    # 3. Verify message in DB
    media_message = Message.query.filter_by(content_type='photo').first()
    assert media_message is not None
    assert media_message.body == 'Check out this pic!'
    assert media_message.content_path == upload_data['content_path']

    # 4. Verify rendered HTML
    response = client.get(f'/chat/{convo.id}')
    assert response.status_code == 200
    assert bytes(upload_data['content_path'], 'utf-8') in response.data
    assert b'chat-media-photo' in response.data

def test_delete_message(client, app):
    """Test deleting a message for everyone."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    message_to_delete = Message(conversation=convo, sender=user1, body="This will be deleted.")
    db.session.add_all([convo, p1, message_to_delete])
    db.session.commit()

    message_id = message_to_delete.id
    assert Message.query.get(message_id) is not None

    login(client, 'user1', 'pw')

    # Listen for the socket event
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})

    # Call the delete route
    response = client.post(f'/chat/message/{message_id}/delete')
    assert response.status_code == 200

    # Verify message is deleted from DB
    assert Message.query.get(message_id) is None

    # Verify socket event was broadcast
    received = socketio_client.get_received()
    assert received[0]['name'] == 'message_deleted'
    assert received[0]['args'][0]['message_id'] == message_id

def test_send_shared_post_message(client, app):
    """Test sending a message that shares a post."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')
    post_author = register_user(username='poster', email='poster@test.com', password='pw')

    # Create conversation and post
    convo = Conversation()
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    shared_post = Post(author=post_author, content_type='text', text='A post to be shared', mode='Test')
    db.session.add_all([convo, p1, p2, shared_post])
    db.session.commit()

    login(client, 'user1', 'pw')
    socketio_client = socketio.test_client(app, flask_test_client=client)
    socketio_client.emit('join', {'room': str(convo.id)})
    socketio_client.emit('send_message', {
        'room': str(convo.id),
        'content_type': 'shared_post',
        'shared_post_id': shared_post.id
    })

    # Check the socket response
    received = socketio_client.get_received()
    assert received[0]['name'] == 'new_message'
    message_data = received[0]['args'][0]
    assert message_data['content_type'] == 'shared_post'
    assert message_data['shared_post']['id'] == shared_post.id
    assert message_data['shared_post']['author_name'] == post_author.full_name

    # Check the database
    message = Message.query.filter_by(content_type='shared_post').first()
    assert message is not None
    assert message.shared_post_id == shared_post.id

    # Check the rendered HTML
    response = client.get(f'/chat/{convo.id}')
    assert response.status_code == 200
    assert b'shared-post-card' in response.data
    assert bytes(shared_post.text, 'utf-8') in response.data
    assert bytes(post_author.full_name, 'utf-8') in response.data

def test_create_group_chat_and_verify_admin(client):
    """Test that the creator of a group is made an admin."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    client.post('/chat/create_group', data={
        'group_name': 'Admin Test Group',
        'members': [user2.id]
    }, follow_redirects=True)

    group_convo = Conversation.query.filter_by(name='Admin Test Group').first()
    assert group_convo is not None

    creator_participant = Participant.query.filter_by(user_id=user1.id, conversation_id=group_convo.id).first()
    assert creator_participant.role == 'admin'

    other_participant = Participant.query.filter_by(user_id=user2.id, conversation_id=group_convo.id).first()
    assert other_participant.role == 'member'

def test_admin_can_edit_group_info(client):
    """Test that an admin can edit group info."""
    admin = register_user(username='admin', email='admin@test.com', password='pw')
    convo = Conversation(is_group=True, name='Original Name')
    p = Participant(user=admin, conversation=convo, role='admin')
    db.session.add_all([convo, p])
    db.session.commit()

    login(client, 'admin', 'pw')
    response = client.post(f'/chat/{convo.id}/edit', data={
        'group_name': 'New Name',
        'description': 'New Description'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Group information updated successfully' in response.data
    db.session.refresh(convo)
    assert convo.name == 'New Name'
    assert convo.description == 'New Description'

def test_non_admin_cannot_edit_group_info(client):
    """Test that a non-admin cannot edit group info."""
    admin = register_user(username='admin', email='admin@test.com', password='pw')
    member = register_user(username='member', email='member@test.com', password='pw')
    convo = Conversation(is_group=True, name='Original Name')
    p1 = Participant(user=admin, conversation=convo, role='admin')
    p2 = Participant(user=member, conversation=convo, role='member')
    db.session.add_all([convo, p1, p2])
    db.session.commit()

    login(client, 'member', 'pw')
    response = client.post(f'/chat/{convo.id}/edit', data={'group_name': 'Attempted New Name'}, follow_redirects=True)

    assert response.status_code == 200
    assert b'You do not have permission' in response.data
    db.session.refresh(convo)
    assert convo.name == 'Original Name'

def test_admin_can_manage_members(client):
    """Test that an admin can add, remove, promote, and demote members."""
    admin = register_user(username='admin', email='admin@test.com', password='pw')
    member1 = register_user(username='member1', email='m1@test.com', password='pw')
    member2 = register_user(username='member2', email='m2@test.com', password='pw')
    convo = Conversation(is_group=True, name='Management Test')
    p_admin = Participant(user=admin, conversation=convo, role='admin')
    p_member1 = Participant(user=member1, conversation=convo, role='member')
    db.session.add_all([convo, p_admin, p_member1])
    db.session.commit()

    login(client, 'admin', 'pw')

    # Add member2
    client.post(f'/chat/{convo.id}/add_members', data={'members': [member2.id]})
    p_member2 = Participant.query.filter_by(user_id=member2.id, conversation_id=convo.id).first()
    assert p_member2 is not None

    # Promote member1
    client.post(f'/chat/participant/{p_member1.id}/promote')
    db.session.refresh(p_member1)
    assert p_member1.role == 'admin'

    # Demote member1
    client.post(f'/chat/participant/{p_member1.id}/demote')
    db.session.refresh(p_member1)
    assert p_member1.role == 'member'

    # Remove member2
    client.post(f'/chat/participant/{p_member2.id}/remove')
    p_member2_after_remove = Participant.query.filter_by(user_id=member2.id, conversation_id=convo.id).first()
    assert p_member2_after_remove is None

def test_member_can_leave_group(client):
    """Test that a member can leave a group."""
    admin = register_user(username='admin', email='admin@test.com', password='pw')
    member = register_user(username='member', email='member@test.com', password='pw')
    convo = Conversation(is_group=True, name='Leave Test')
    p_admin = Participant(user=admin, conversation=convo, role='admin')
    p_member = Participant(user=member, conversation=convo, role='member')
    db.session.add_all([convo, p_admin, p_member])
    db.session.commit()

    login(client, 'member', 'pw')
    client.post(f'/chat/conversation/{convo.id}/leave')

    p_member_after_leave = Participant.query.filter_by(user_id=member.id, conversation_id=convo.id).first()
    assert p_member_after_leave is None
    assert Conversation.query.get(convo.id) is not None # Group should still exist

def test_last_admin_leaves_promotes_new_admin(client):
    """Test that when the last admin leaves, another member is promoted."""
    admin = register_user(username='admin', email='admin@test.com', password='pw')
    member = register_user(username='member', email='member@test.com', password='pw')
    convo = Conversation(is_group=True, name='Promotion Test')
    p_admin = Participant(user=admin, conversation=convo, role='admin')
    p_member = Participant(user=member, conversation=convo, role='member')
    db.session.add_all([convo, p_admin, p_member])
    db.session.commit()

    login(client, 'admin', 'pw')
    client.post(f'/chat/conversation/{convo.id}/leave')

    db.session.refresh(p_member)
    assert p_member.role == 'admin'
