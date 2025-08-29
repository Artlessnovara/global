import pytest
from datetime import date
from app import app, socketio, db, User, Conversation, Participant

def test_webrtc_signaling_flow(app):
    """
    Test the full WebRTC signaling flow between two clients.
    This test verifies that the server correctly relays signaling messages.
    """
    # --- Setup ---
    user1 = User(id=1, full_name='User1', username='user1', email='u1@test.com', date_of_birth=date(2000, 1, 1))
    user1.set_password('pw')
    user2 = User(id=2, full_name='User2', username='user2', email='u2@test.com', date_of_birth=date(2000, 1, 1))
    user2.set_password('pw')
    convo = Conversation(id=1)
    p1 = Participant(user=user1, conversation=convo)
    p2 = Participant(user=user2, conversation=convo)
    db.session.add_all([user1, user2, convo, p1, p2])
    db.session.commit()

    with app.test_client() as client1:
        with app.test_client() as client2:
            # --- Client 1 (Caller) ---
            response1 = client1.post('/login', data={'username': 'user1', 'password': 'pw'})
            cookie1 = response1.headers.get('Set-Cookie').split(';')[0]
            headers1 = {'Cookie': cookie1}
            caller_client = socketio.test_client(app, headers=headers1)
            assert caller_client.is_connected()

            # --- Client 2 (Callee) ---
            response2 = client2.post('/login', data={'username': 'user2', 'password': 'pw'})
            cookie2 = response2.headers.get('Set-Cookie').split(';')[0]
            headers2 = {'Cookie': cookie2}
            callee_client = socketio.test_client(app, headers=headers2)
            assert callee_client.is_connected()

            # --- Test Signaling ---
            # Both clients join the conversation room
            caller_client.emit('join', {'room': str(convo.id)})
            callee_client.emit('join', {'room': str(convo.id)})

            # 1. Caller sends an offer
            offer_data = {'sdp': 'dummy_offer'}
            caller_client.emit('call-user', {'to': str(convo.id), 'offer': offer_data})

            # 2. Callee should receive the 'call-made' event
            received_by_callee = callee_client.get_received()
            call_made_events = [e for e in received_by_callee if e['name'] == 'call-made']
            assert len(call_made_events) > 0
            assert call_made_events[0]['args'][0]['offer'] == offer_data
            caller_sid = call_made_events[0]['args'][0]['sid'] # Save the caller's SID

            # 3. Callee sends an answer
            answer_data = {'sdp': 'dummy_answer'}
            callee_client.emit('make-answer', {'to': caller_sid, 'answer': answer_data})

            # 4. Caller should receive the 'answer-made' event
            received_by_caller = caller_client.get_received()
            answer_made_events = [e for e in received_by_caller if e['name'] == 'answer-made']
            assert len(answer_made_events) > 0
            assert answer_made_events[0]['args'][0]['answer'] == answer_data

            # 5. Test ICE candidate relay
            candidate_data = {'candidate': 'dummy_candidate'}
            caller_client.emit('ice-candidate', {'to': str(convo.id), 'candidate': candidate_data})

            # 6. Callee should receive the 'ice-candidate' event
            received_by_callee = callee_client.get_received()
            ice_candidate_events = [e for e in received_by_callee if e['name'] == 'ice-candidate']
            assert len(ice_candidate_events) > 0
            assert ice_candidate_events[0]['args'][0]['candidate'] == candidate_data

            caller_client.disconnect()
            callee_client.disconnect()
