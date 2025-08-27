import pytest
from app import app as flask_app, db as database, Mode

@pytest.fixture(scope='function')
def app(request):
    """Function-scoped test `Flask` application."""
    flask_app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///test.db", # Use a file-based DB for tests
        "WTF_CSRF_ENABLED": False,
    })
    yield flask_app

@pytest.fixture(scope='function')
def _db(app):
    """Function-scoped database setup. Creates and drops tables for each test."""
    with app.app_context():
        database.create_all()
    yield database
    with app.app_context():
        database.drop_all()

@pytest.fixture(scope='function', autouse=True)
def session(app, _db, monkeypatch):
    """
    Wraps each test in a transaction and monkeypatches the db.session
    object to use this transactional session. Rolls back at the end.
    """
    with app.app_context():
        connection = _db.engine.connect()
        transaction = connection.begin()

        test_session = _db._make_scoped_session(options={'bind': connection})
        monkeypatch.setattr(database, 'session', test_session)

        yield test_session

        test_session.remove()
        transaction.rollback()
        connection.close()

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()

@pytest.fixture
def seed_db(session):
    """Seed the database with initial data for tests."""
    modes_to_add = [
        'Education', 'Music', 'Artist', 'Innovation', 'Sports', 'Welfare',
        'Fun', 'Job', 'Blog/Article', 'Podcast/Audio', 'Gaming',
        'Community/Forum', 'Business/Marketplace', 'Event', 'News/Update',
        'Wellness', 'Creativity', 'Civic/Leadership', 'Networking'
    ]
    for mode_name in modes_to_add:
        if not Mode.query.filter_by(name=mode_name).first():
            new_mode = Mode(name=mode_name)
            session.add(new_mode)
    session.commit()
