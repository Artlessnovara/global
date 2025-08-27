import os
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import click
from flask.cli import with_appcontext
from functools import wraps
import humanize
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)

@app.template_filter('humanize_time')
def _jinja2_filter_humanize_time(dt):
    now_utc = datetime.utcnow()
    if dt > now_utc:
        return "in the future"
    return humanize.naturaltime(now_utc - dt)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///glooba.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('users.id'))
)

user_modes = db.Table('user_modes',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('mode_id', db.Integer, db.ForeignKey('modes.id'), primary_key=True)
)

# --- DATABASE MODELS ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    cover_photo_path = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    work_education = db.Column(db.String(150), nullable=True)
    country = db.Column(db.String(100), nullable=True)

    posts = db.relationship('Post', backref='author', lazy='dynamic')
    stories = db.relationship('Story', backref='author', lazy=True)
    reactions = db.relationship('Reaction', backref='user', lazy='dynamic')
    conversations = db.relationship('Participant', cascade="all, delete-orphan")
    preferred_modes = db.relationship('Mode', secondary=user_modes, lazy='subquery', backref=db.backref('users', lazy=True))

    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    def is_following(self, user):
        return self.followed.filter(
            followers.c.followed_id == user.id).count() > 0

    def has_reacted_to(self, post):
        return Reaction.query.filter(
            Reaction.user_id == self.id,
            Reaction.post_id == post.id).count() > 0

class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content_type = db.Column(db.String(10), nullable=False)
    content_path = db.Column(db.String(255), nullable=True)
    text = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reactions = db.relationship('Reaction', backref='post', lazy='dynamic')

class Story(db.Model):
    __tablename__ = 'stories'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    media_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24), nullable=False)

class Reaction(db.Model):
    __tablename__ = 'reactions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)

class Mode(db.Model):
    __tablename__ = 'modes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)

class Participant(db.Model):
    __tablename__ = 'participants'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    last_read_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')
    conversation = db.relationship('Conversation')

class Conversation(db.Model):
    __tablename__ = 'conversations'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")
    participants = db.relationship('Participant', cascade="all, delete-orphan")

    def unread_messages_for(self, user):
        participant = next((p for p in self.participants if p.user_id == user.id), None)
        if not participant or not participant.last_read_at:
            return self.messages.count()
        return self.messages.filter(Message.created_at > participant.last_read_at).count()

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversations.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User')

# --- CLI COMMANDS ---
@click.command('init-db')
@with_appcontext
def init_db_command():
    """Clear the existing data and create new tables."""
    db.drop_all()
    db.create_all()

    modes_to_add = [
        'Education', 'Music', 'Artist', 'Innovation', 'Sports', 'Welfare',
        'Fun', 'Job', 'Blog/Article', 'Podcast/Audio', 'Gaming',
        'Community/Forum', 'Business/Marketplace', 'Event', 'News/Update',
        'Wellness', 'Creativity', 'Civic/Leadership', 'Networking'
    ]
    for mode_name in modes_to_add:
        new_mode = Mode(name=mode_name)
        db.session.add(new_mode)

    db.session.commit()
    click.echo('Initialized the database and seeded modes.')
app.cli.add_command(init_db_command)

# --- AUTH HELPERS & DECORATORS ---
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = db.session.get(User, user_id)

@app.context_processor
def inject_unread_count():
    if g.user:
        total_unread = 0
        for p_entry in g.user.conversations:
            total_unread += p_entry.conversation.unread_messages_for(g.user)
        return dict(total_unread_messages=total_unread)
    return dict(total_unread_messages=0)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- ROUTES ---
@app.route('/')
def loading():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('loading.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('home'))
    if request.method == 'POST':
        login_identifier = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter((User.username == login_identifier) | (User.email == login_identifier)).first()
        if user and user.check_password(password):
            session.clear()
            session['user_id'] = user.id
            return redirect(url_for('home'))
        else:
            flash('Invalid username/email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/follow/<int:user_id>')
@login_required
def follow(user_id):
    user_to_follow = db.get_or_404(User, user_id)
    if user_to_follow != g.user:
        g.user.follow(user_to_follow)
        db.session.commit()
        flash(f'You are now following {user_to_follow.username}.', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/unfollow/<int:user_id>')
@login_required
def unfollow(user_id):
    user_to_unfollow = db.get_or_404(User, user_id)
    if user_to_unfollow != g.user:
        g.user.unfollow(user_to_unfollow)
        db.session.commit()
        flash(f'You have unfollowed {user_to_unfollow.username}.', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/react/<int:post_id>')
@login_required
def react(post_id):
    post = db.get_or_404(Post, post_id)
    existing_reaction = Reaction.query.filter_by(user_id=g.user.id, post_id=post.id).first()
    if existing_reaction:
        db.session.delete(existing_reaction)
    else:
        new_reaction = Reaction(user_id=g.user.id, post_id=post.id)
        db.session.add(new_reaction)
    db.session.commit()
    return redirect(request.referrer or url_for('home'))

@app.route('/signup', methods=['GET'])
def signup():
    session.pop('signup_form', None)
    return redirect(url_for('signup_step', step=1))

@app.route('/signup/<int:step>', methods=['GET', 'POST'])
def signup_step(step):
    if 'signup_form' not in session:
        session['signup_form'] = {}
    if request.method == 'POST':
        for key, value in request.form.items():
            if value:
                session['signup_form'][key] = value
        if step == 2:
            email = session['signup_form'].get('email')
            phone = session['signup_form'].get('phone')
            if not email and not phone:
                flash('Please provide an email or a phone number.', 'error')
                return redirect(url_for('signup_step', step=2))
            if email and User.query.filter_by(email=email).first():
                flash('Email address already in use.', 'error')
                return redirect(url_for('signup_step', step=2))
            if phone and User.query.filter_by(phone=phone).first():
                flash('Phone number already in use.', 'error')
                return redirect(url_for('signup_step', step=2))
        elif step == 3:
            username = session['signup_form'].get('username')
            if User.query.filter_by(username=username).first():
                flash('Username is already taken.', 'error')
                return redirect(url_for('signup_step', step=3))
        elif step == 5:
            if session['signup_form'].get('password') != session['signup_form'].get('confirm_password'):
                flash('Passwords do not match.', 'error')
                session['signup_form'].pop('password', None)
                session['signup_form'].pop('confirm_password', None)
                return redirect(url_for('signup_step', step=4))
        elif step == 6:
            try:
                form_data = session['signup_form']
                dob = datetime.strptime(form_data.get('date_of_birth'), '%Y-%m-%d').date()
                new_user = User(full_name=form_data.get('full_name'), username=form_data.get('username'), email=form_data.get('email'), phone=form_data.get('phone'), date_of_birth=dob)
                new_user.set_password(form_data.get('password'))
                db.session.add(new_user)
                db.session.commit()
                flash('Account created successfully! Please log in.', 'success')
                session.pop('signup_form', None)
                return redirect(url_for('login'))
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred: {e}', 'error')
                return redirect(url_for('signup'))
        next_step = step + 1
        if next_step > 6:
            return redirect(url_for('home'))
        return redirect(url_for('signup_step', step=next_step))
    return render_template('signup.html', step=step, form_data=session.get('signup_form', {}))

@app.route('/create_post', methods=['POST'])
@login_required
def create_post():
    text_content = request.form.get('text_content')
    mode = request.form.get('mode')
    if not text_content or not mode:
        flash('Content and mode are required to create a post.', 'error')
        return redirect(url_for('home'))
    new_post = Post(user_id=g.user.id, content_type='text', text=text_content, mode=mode)
    db.session.add(new_post)
    db.session.commit()
    flash('Your post has been created!', 'success')
    return redirect(url_for('home'))

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    stats = {'posts': user.posts.count(), 'followers': user.followers.count(), 'following': user.followed.count()}
    posts = user.posts.order_by(Post.created_at.desc()).all()
    return render_template('profile.html', user=user, stats=stats, posts=posts)

@app.route('/home')
@login_required
def home():
    stories = Story.query.join(followers, (followers.c.followed_id == Story.user_id)).filter(followers.c.follower_id == g.user.id).order_by(Story.created_at.desc()).all()
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('home.html', stories=stories, posts=posts)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        selected_mode_ids = request.form.getlist('modes')
        g.user.preferred_modes = []
        for mode_id in selected_mode_ids:
            mode = db.session.get(Mode, int(mode_id))
            if mode:
                g.user.preferred_modes.append(mode)
        db.session.commit()
        flash('Your preferences have been updated.', 'success')
        return redirect(url_for('settings'))
    all_modes = Mode.query.order_by(Mode.name).all()
    user_mode_ids = [mode.id for mode in g.user.preferred_modes]
    return render_template('settings.html', available_modes=all_modes, user_mode_ids=user_mode_ids)

@app.route('/more')
@login_required
def more():
    return render_template('more.html')

@app.route('/modes/my')
@login_required
def my_modes():
    return render_template('my_modes.html')

@app.route('/modes/discover')
@login_required
def discover_modes():
    all_modes = Mode.query.order_by(Mode.name).all()
    return render_template('discover_modes.html', modes=all_modes)

@app.route('/suggestions')
@login_required
def suggestions():
    preferred_modes = g.user.preferred_modes
    suggested_users = []
    if preferred_modes:
        modes_list = [mode.name for mode in preferred_modes]
        followed_user_ids = [user.id for user in g.user.followed]
        suggested_users = db.session.query(User).join(Post).filter(Post.mode.in_(modes_list), User.id != g.user.id, ~User.id.in_(followed_user_ids)).distinct().limit(20).all()
    return render_template('suggestions.html', suggested_users=suggested_users)

@app.route('/chat/<int:conversation_id>')
@login_required
def message_thread(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant_users = [p.user for p in convo.participants]
    if g.user not in participant_users:
        return "Not your conversation", 403
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)
    if participant:
        participant.last_read_at = datetime.utcnow()
        db.session.commit()
    messages = convo.messages.order_by(Message.created_at.asc()).all()
    other_user = next((p.user for p in convo.participants if p.user_id != g.user.id), None)
    return render_template('message_thread.html', conversation=convo, messages=messages, other_user=other_user)

@app.route('/chat/start/<int:user_id>')
@login_required
def start_chat(user_id):
    other_user = db.get_or_404(User, user_id)
    if other_user == g.user:
        flash("You cannot start a chat with yourself.", "error")
        return redirect(url_for('profile', username=g.user.username))
    user_participant_entries = g.user.conversations
    existing_convo = None
    for p_entry in user_participant_entries:
        convo = p_entry.conversation
        if len(convo.participants) == 2:
            other_participant = next((p for p in convo.participants if p.user_id != g.user.id), None)
            if other_participant and other_participant.user_id == other_user.id:
                existing_convo = convo
                break
    if existing_convo:
        return redirect(url_for('message_thread', conversation_id=existing_convo.id))
    else:
        new_convo = Conversation()
        p1 = Participant(user=g.user, conversation=new_convo)
        p2 = Participant(user=other_user, conversation=new_convo)
        db.session.add_all([p1, p2])
        db.session.commit()
        return redirect(url_for('message_thread', conversation_id=new_convo.id))

@app.route('/chat')
@login_required
def chat_inbox():
    user_participant_entries = g.user.conversations
    return render_template('chat_inbox.html', participant_entries=user_participant_entries, Message=Message)

@app.route('/reels')
@login_required
def reels():
    video_posts = Post.query.filter_by(content_type='video').order_by(Post.created_at.desc()).all()
    return render_template('reels.html', posts=video_posts)

# --- SOCKETIO EVENTS ---
@socketio.on('send_message')
def handle_send_message_event(data):
    user_id = session.get('user_id')
    if not user_id: return
    user = db.session.get(User, user_id)
    convo = db.get_or_404(Conversation, data['room'])
    participant_users = [p.user for p in convo.participants]
    if user not in participant_users:
        return
    new_message = Message(conversation_id=data['room'], user_id=user_id, body=data['message'])
    db.session.add(new_message)
    db.session.commit()
    message_data = {'body': new_message.body, 'author_name': new_message.sender.full_name, 'author_username': new_message.sender.username, 'user_id': new_message.user_id}
    emit('new_message', message_data, room=data['room'])

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)

@socketio.on('leave')
def on_leave(data):
    room = data['room']
    leave_room(room)

if __name__ == '__main__':
    socketio.run(app, debug=True)
