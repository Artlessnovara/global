import pytest
from app import app as flask_app, db, socketio, Mode

@pytest.fixture
def app():
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", # Use in-memory SQLite for tests
        "WTF_CSRF_ENABLED": False # Disable CSRF for testing forms
    })

    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def runner(app):
    return app.test_cli_runner()

@pytest.fixture
def seed_db(app):
    """Seed the database with initial data for tests."""
    with app.app_context():
        modes_to_add = [
            'Education', 'Music', 'Artist', 'Innovation', 'Sports', 'Welfare',
            'Fun', 'Job', 'Blog/Article', 'Podcast/Audio', 'Gaming',
            'Community/Forum', 'Business/Marketplace', 'Event', 'News/Update',
            'Wellness', 'Creativity', 'Civic/Leadership', 'Networking'
        ]
        for mode_name in modes_to_add:
            # Check if mode already exists to prevent duplicates if fixture is used multiple times
            if not Mode.query.filter_by(name=mode_name).first():
                new_mode = Mode(name=mode_name)
                db.session.add(new_mode)
        db.session.commit()
