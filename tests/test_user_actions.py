import pytest
from tests.test_auth import register_user, login
from app import db, User, BlockedUser, Report

def test_block_and_unblock_user(client):
    """Test blocking and then unblocking a user."""
    user1 = register_user(username='user1', email='user1@test.com', password='pw')
    user2 = register_user(username='user2', email='user2@test.com', password='pw')

    login(client, 'user1', 'pw')

    # Block user2
    response = client.post(f'/users/{user2.id}/block')
    assert response.status_code == 200
    assert response.json['status'] == 'blocked'

    block = BlockedUser.query.filter_by(blocker_id=user1.id, blocked_id=user2.id).first()
    assert block is not None

    # Unblock user2
    response = client.post(f'/users/{user2.id}/block')
    assert response.status_code == 200
    assert response.json['status'] == 'unblocked'

    block = BlockedUser.query.filter_by(blocker_id=user1.id, blocked_id=user2.id).first()
    assert block is None

def test_report_user(client):
    """Test reporting a user."""
    user1 = register_user(username='reporter', email='reporter@test.com', password='pw')
    user2 = register_user(username='reported', email='reported@test.com', password='pw')

    login(client, 'reporter', 'pw')

    report_data = {
        'reported_user_id': user2.id,
        'reason': 'This is a test report.'
    }
    response = client.post('/report', json=report_data)

    assert response.status_code == 201
    assert response.json['status'] == 'success'

    report = Report.query.filter_by(reporter_id=user1.id, reported_user_id=user2.id).first()
    assert report is not None
    assert report.reason == 'This is a test report.'
