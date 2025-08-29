import pytest
import os
from io import BytesIO
from app import app, db
from tests.test_auth import login, register_user

def test_upload_chat_file(client):
    """Test uploading a file to the chat media endpoint."""
    user = register_user(username='uploader', email='uploader@test.com', password='pw')
    login(client, 'uploader', 'pw')

    data = {
        'file': (BytesIO(b"dummy file content"), 'test.txt')
    }

    response = client.post('/chat/upload_file', data=data, content_type='multipart/form-data')

    assert response.status_code == 200
    json_data = response.get_json()
    assert 'file_path' in json_data
    assert 'chat_media' in json_data['file_path']
    assert 'test.txt' in json_data['file_path']

    # Check if the file was actually created
    file_path = os.path.join(app.static_folder, json_data['file_path'])
    assert os.path.exists(file_path)

    # Clean up the created file
    os.remove(file_path)
