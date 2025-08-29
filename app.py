import os
from datetime import datetime, timedelta, date, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload, aliased
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import click
from flask.cli import with_appcontext
from functools import wraps
import humanize
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_migrate import Migrate

app = Flask(__name__)

@app.template_filter('humanize_time')
def _jinja2_filter_humanize_time(dt):
    now_utc = datetime.now(timezone.utc)
    # If the datetime is naive, make it aware (assuming it's UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    if dt > now_utc:
        return "in the future"
    return humanize.naturaltime(now_utc - dt)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///glooba.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)
migrate = Migrate(app, db)

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('users.id'))
)

user_modes = db.Table('user_modes',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('mode_id', db.Integer, db.ForeignKey('modes.id'), primary_key=True)
)

close_friends = db.Table('close_friends',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('close_friend_id', db.Integer, db.ForeignKey('users.id'), primary_key=True)
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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_premium = db.Column(db.Boolean, default=False, nullable=False)
    cover_photo_path = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    work_education = db.Column(db.String(150), nullable=True)
    relationship_status = db.Column(db.String(50), nullable=True)
    country = db.Column(db.String(100), nullable=True)

    posts = db.relationship('Post', backref='author', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    stories = db.relationship('Story', backref='author', lazy=True)
    reactions = db.relationship('Reaction', backref='user', lazy='dynamic')
    conversations = db.relationship('Participant', back_populates='user', cascade="all, delete-orphan")
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

    close_friends = db.relationship(
        'User',
        secondary=close_friends,
        primaryjoin=(close_friends.c.user_id == id),
        secondaryjoin=(close_friends.c.close_friend_id == id),
        backref=db.backref('close_friend_of', lazy='dynamic'),
        lazy='dynamic'
    )

    def add_close_friend(self, user):
        if not self.is_close_friend(user):
            self.close_friends.append(user)

    def remove_close_friend(self, user):
        if self.is_close_friend(user):
            self.close_friends.remove(user)

    def is_close_friend(self, user):
        return self.close_friends.filter(
            close_friends.c.close_friend_id == user.id).count() > 0

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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reactions = db.relationship('Reaction', backref='post', lazy='dynamic')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade="all, delete-orphan")

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False)

class Story(db.Model):
    __tablename__ = 'stories'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    media_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(hours=24), nullable=False)

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
    last_read_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    status = db.Column(db.String(20), default='active', nullable=False) # active, pending, blocked
    role = db.Column(db.String(20), nullable=False, default='member') # 'admin', 'member', 'host', 'co-host', 'listener'
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    user = db.relationship('User', back_populates='conversations')
    conversation = db.relationship('Conversation', back_populates='participants')

import secrets

class Conversation(db.Model):
    __tablename__ = 'conversations'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_group = db.Column(db.Boolean, default=False, nullable=False)
    name = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    group_photo_path = db.Column(db.String(255), nullable=True)
    invite_code = db.Column(db.String(16), unique=True, default=lambda: secrets.token_urlsafe(12))
    is_invite_link_enabled = db.Column(db.Boolean, default=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    disappearing_timer_seconds = db.Column(db.Integer, nullable=True)
    messages = db.relationship('Message', backref='conversation', lazy='dynamic', cascade="all, delete-orphan")
    participants = db.relationship('Participant', back_populates='conversation', cascade="all, delete-orphan")

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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sender = db.relationship('User')

class MessageReaction(db.Model):
    __tablename__ = 'message_reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reaction = db.Column(db.String(10), nullable=False) # e.g., '❤️', '😂'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship('User')
    message = db.relationship('Message', backref=db.backref('reactions', lazy='dynamic', cascade="all, delete-orphan"))

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id')) # Can be null for system notifications
    type = db.Column(db.String(50), nullable=False) # e.g., 'like', 'follow', 'comment'
    related_id = db.Column(db.Integer) # e.g., post_id, user_id
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='notifications')
    sender = db.relationship('User', foreign_keys=[sender_id])

    # Define a relationship to the Post model for 'like' notifications
    related_post = db.relationship('Post',
        primaryjoin="and_(Notification.type=='like', foreign(Notification.related_id)==Post.id)",
        uselist=False,
        viewonly=True)

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
        # Unread messages
        participant_entries = Participant.query.filter_by(user_id=g.user.id).all()
        total_unread_messages = 0
        for p_entry in participant_entries:
            if p_entry.status == 'active':
                total_unread_messages += p_entry.conversation.unread_messages_for(g.user)

        # Unread notifications
        total_unread_notifications = Notification.query.filter_by(recipient_id=g.user.id, is_read=False).count()

        return dict(
            total_unread_messages=total_unread_messages,
            total_unread_notifications=total_unread_notifications
        )
    return dict(total_unread_messages=0, total_unread_notifications=0)

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
        # Create a notification for the user who was followed
        notification = Notification(
            recipient_id=user_to_follow.id,
            sender_id=g.user.id,
            type='follow'
        )
        db.session.add(notification)

        # Check for follower milestones for achievement notifications
        follower_count = user_to_follow.followers.count()
        milestones = [10, 100, 1000, 10000] # Define milestones
        if follower_count in milestones:
            achievement_notif = Notification(
                recipient_id=user_to_follow.id,
                type='achievement',
                related_id=follower_count # Store the milestone number
            )
            db.session.add(achievement_notif)

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

@app.route('/add_close_friend/<int:user_id>')
@login_required
def add_close_friend(user_id):
    user_to_add = db.get_or_404(User, user_id)
    if user_to_add != g.user:
        g.user.add_close_friend(user_to_add)
        db.session.commit()
        flash(f'{user_to_add.username} has been added to your Close Friends.', 'success')
    return redirect(request.referrer or url_for('profile', username=user_to_add.username))

@app.route('/remove_close_friend/<int:user_id>')
@login_required
def remove_close_friend(user_id):
    user_to_remove = db.get_or_404(User, user_id)
    if user_to_remove != g.user:
        g.user.remove_close_friend(user_to_remove)
        db.session.commit()
        flash(f'{user_to_remove.username} has been removed from your Close Friends.', 'success')
    return redirect(request.referrer or url_for('profile', username=user_to_remove.username))

@app.route('/react/<int:post_id>')
@login_required
def react(post_id):
    post = db.get_or_404(Post, post_id)
    existing_reaction = Reaction.query.filter_by(user_id=g.user.id, post_id=post.id).first()
    if existing_reaction:
        db.session.delete(existing_reaction)
        # Optional: could add logic to delete the corresponding 'like' notification
    else:
        new_reaction = Reaction(user_id=g.user.id, post_id=post.id)
        db.session.add(new_reaction)
        # Create a notification for the post author, but not if they are liking their own post
        if post.author.id != g.user.id:
            notification = Notification(
                recipient_id=post.author.id,
                sender_id=g.user.id,
                type='like',
                related_id=post.id
            )
            db.session.add(notification)
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
        session.modified = True # Ensure session changes are saved

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
        elif step == 4:
            password = session.get('signup_form', {}).get('password')
            if not password:
                flash('Password cannot be empty.', 'error')
                return redirect(url_for('signup_step', step=4))
        elif step == 5:
            if 'password' not in session.get('signup_form', {}):
                flash('An error occurred. Please enter your password again.', 'error')
                return redirect(url_for('signup_step', step=4))
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
        if next_step > 5:
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

    # Fetch photo and video posts for the new tabbed view
    photo_posts = user.posts.filter_by(content_type='photo').order_by(Post.created_at.desc()).all()
    video_posts = user.posts.filter_by(content_type='video').order_by(Post.created_at.desc()).all()

    return render_template('profile.html', user=user, stats=stats, photo_posts=photo_posts, video_posts=video_posts)

@app.route('/create')
@login_required
def create_choice():
    """Display the choice page for creating a new photo or video post."""
    return render_template('create_choice.html')

@app.route('/create/<media_type>', methods=['GET', 'POST'])
@login_required
def create_media_post(media_type):
    if media_type not in ['photo', 'video']:
        return "Invalid media type", 404

    if request.method == 'POST':
        if 'media_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['media_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        text_content = request.form.get('text_content', '')
        mode = request.form.get('mode')
        if not mode:
            flash('A mode is required for all posts.', 'error')
            return redirect(request.url)

        if file:
            filename = secure_filename(file.filename)
            posts_dir = os.path.join(app.static_folder, 'posts')
            os.makedirs(posts_dir, exist_ok=True)

            unique_filename = f"{g.user.id}_{int(datetime.now(timezone.utc).timestamp())}_{filename}"
            file_path = os.path.join(posts_dir, unique_filename)
            file.save(file_path)

            relative_path = os.path.join('posts', unique_filename)
            new_post = Post(
                user_id=g.user.id,
                content_type=media_type,
                content_path=relative_path,
                text=text_content,
                mode=mode
            )
            db.session.add(new_post)
            db.session.commit()

            flash(f'Your {media_type} has been posted!', 'success')
            return redirect(url_for('profile', username=g.user.username))

    return render_template('create_media_post.html', media_type=media_type)

@app.route('/home')
@login_required
def home():
    stories = Story.query.join(followers, (followers.c.followed_id == Story.user_id)).filter(followers.c.follower_id == g.user.id).order_by(Story.created_at.desc()).all()
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('home.html', stories=stories, posts=posts)

@app.route('/create_story', methods=['GET', 'POST'])
@login_required
def create_story():
    if request.method == 'POST':
        if 'story_file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['story_file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file:
            filename = secure_filename(file.filename)
            # Ensure stories directory exists
            stories_dir = os.path.join(app.static_folder, 'stories')
            os.makedirs(stories_dir, exist_ok=True)

            # To make filenames unique, prepend user_id and timestamp
            unique_filename = f"{g.user.id}_{int(datetime.now(timezone.utc).timestamp())}_{filename}"
            file_path = os.path.join(stories_dir, unique_filename)
            file.save(file_path)

            # Create story record in the database
            relative_path = os.path.join('stories', unique_filename)
            new_story = Story(user_id=g.user.id, media_path=relative_path)
            db.session.add(new_story)
            db.session.commit()

            flash('Your story has been uploaded!', 'success')
            return redirect(url_for('home'))

    return render_template('create_story.html')

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
        participant.last_read_at = datetime.now(timezone.utc)
        db.session.commit()

    messages_query = convo.messages.order_by(Message.created_at.asc())

    # Filter for disappearing messages
    if convo.disappearing_timer_seconds:
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=convo.disappearing_timer_seconds)
        messages_query = messages_query.filter(Message.created_at >= cutoff_time)

    messages = messages_query.all()
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
        p1_status = 'active'
        p2_status = 'active' if other_user.is_following(g.user) else 'pending'
        p1 = Participant(user=g.user, conversation=new_convo, status=p1_status)
        p2 = Participant(user=other_user, conversation=new_convo, status=p2_status)
        db.session.add_all([new_convo, p1, p2])
        db.session.commit()
        return redirect(url_for('message_thread', conversation_id=new_convo.id))

@app.route('/chat/accept/<int:conversation_id>')
@login_required
def accept_chat(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)
    if participant and participant.status == 'pending':
        participant.status = 'active'
        db.session.commit()
        flash('Chat request accepted.', 'success')
        return redirect(url_for('message_thread', conversation_id=conversation_id))
    return redirect(url_for('chat_inbox'))

@app.route('/chat/delete/<int:conversation_id>')
@login_required
def delete_chat(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant_users = [p.user for p in convo.participants]
    if g.user not in participant_users:
        return "Not your conversation", 403
    db.session.delete(convo)
    db.session.commit()
    flash('Conversation deleted.', 'success')
    return redirect(url_for('chat_inbox'))

@app.route('/chat/pin/<int:conversation_id>', methods=['POST'])
@login_required
def pin_chat(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)
    if participant:
        participant.is_pinned = not participant.is_pinned
        db.session.commit()
        flash('Chat pin status updated.', 'success')
    return redirect(url_for('chat_inbox'))

@app.route('/chat/archive/<int:conversation_id>', methods=['POST'])
@login_required
def archive_chat(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)
    if participant:
        participant.is_archived = not participant.is_archived
        db.session.commit()
        flash('Chat archive status updated.', 'success')
    return redirect(url_for('chat_inbox'))

@app.route('/chat/search')
@login_required
def chat_search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    # --- Search Users ---
    # Find users you are not already in a 1-on-1 chat with
    # Get IDs of users the current user already has a 1-on-1 chat with
    user_convos = db.session.query(Conversation.id).join(Participant).filter(
        Participant.user_id == g.user.id,
        Conversation.is_group == False
    ).all()
    user_convo_ids = [uc[0] for uc in user_convos]

    other_participants = db.session.query(Participant.user_id).filter(
        Participant.conversation_id.in_(user_convo_ids),
        Participant.user_id != g.user.id
    ).all()
    existing_chat_user_ids = [op[0] for op in other_participants]

    users = User.query.filter(
        ((User.username.ilike(f'%{query}%')) | (User.full_name.ilike(f'%{query}%'))),
        User.id != g.user.id,
        ~User.id.in_(existing_chat_user_ids)
    ).limit(5).all()

    # --- Search Conversations (Groups and 1-on-1) ---
    # Find conversations the user is part of that match the query
    P1 = aliased(Participant)
    P2 = aliased(Participant)
    U2 = aliased(User)

    user_conversations_query = db.session.query(Conversation).join(
        P1, P1.conversation_id == Conversation.id
    ).filter(P1.user_id == g.user.id)

    # Filter for group chats by name
    group_chats = user_conversations_query.filter(
        Conversation.is_group == True,
        Conversation.name.ilike(f'%{query}%')
    )

    # Filter for 1-on-1 chats by other user's name
    one_on_one_chats = user_conversations_query.join(
        P2, P2.conversation_id == Conversation.id
    ).join(
        U2, U2.id == P2.user_id
    ).filter(
        Conversation.is_group == False,
        P2.user_id != g.user.id,
        (U2.full_name.ilike(f'%{query}%') | U2.username.ilike(f'%{query}%'))
    )

    # --- Search Messages ---
    # Find conversations with messages that match the query
    message_chats = user_conversations_query.join(
        Message, Message.conversation_id == Conversation.id
    ).filter(Message.body.ilike(f'%{query}%'))

    # Combine conversation results and remove duplicates
    all_convos = group_chats.union(one_on_one_chats, message_chats).limit(10).all()

    # --- Format Results ---
    results = []
    # Add users (potential new chats)
    for user in users:
        results.append({
            'type': 'user',
            'id': user.id,
            'name': user.full_name,
            'sub_text': f'@{user.username}',
            'avatar': f'https://i.pravatar.cc/150?u={user.username}',
            'url': url_for('start_chat', user_id=user.id)
        })

    # Add conversations
    for convo in all_convos:
        if convo.is_group:
            name = convo.name
            sub_text = f'{len(convo.participants)} members'
            avatar = url_for('static', filename=convo.group_photo_path or 'img/default_group.png')
        else:
            other_user = next((p.user for p in convo.participants if p.user_id != g.user.id), None)
            if not other_user: continue
            name = other_user.full_name
            sub_text = f'Chat with {other_user.username}'
            avatar = f'https://i.pravatar.cc/150?u={other_user.username}'

        results.append({
            'type': 'conversation',
            'id': convo.id,
            'name': name,
            'sub_text': sub_text,
            'avatar': avatar,
            'url': url_for('message_thread', conversation_id=convo.id)
        })

    return jsonify(results)


@app.route('/chat/group/<int:conversation_id>/update', methods=['POST'])
@login_required
def update_group_info(conversation_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not participant or participant.role != 'admin':
        return "You are not an admin of this group.", 403

    name = request.form.get('name')
    description = request.form.get('description')
    photo = request.files.get('photo')

    if name:
        conversation.name = name
    if description:
        conversation.description = description

    if photo:
        filename = secure_filename(photo.filename)
        photo_path = os.path.join('group_photos', f"{conversation.id}_{filename}")
        full_path = os.path.join(app.static_folder, photo_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        photo.save(full_path)
        conversation.group_photo_path = photo_path

    db.session.commit()
    flash('Group info updated successfully.', 'success')
    return redirect(url_for('group_info', conversation_id=conversation.id))

@app.route('/chat/group/<int:conversation_id>/toggle_invite', methods=['POST'])
@login_required
def toggle_invite_link(conversation_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not participant or participant.role != 'admin':
        return {'error': 'Forbidden'}, 403

    conversation.is_invite_link_enabled = not conversation.is_invite_link_enabled
    db.session.commit()

    new_status = 'Enabled' if conversation.is_invite_link_enabled else 'Disabled'
    return {'success': True, 'status': new_status, 'isEnabled': conversation.is_invite_link_enabled}

@app.route('/join/<invite_code>')
@login_required
def join_group_with_invite(invite_code):
    conversation = Conversation.query.filter_by(invite_code=invite_code, is_invite_link_enabled=True).first()
    if not conversation:
        flash('Invalid or expired invite link.', 'error')
        return redirect(url_for('home'))

    existing_participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if existing_participant:
        flash('You are already a member of this group.', 'info')
        return redirect(url_for('message_thread', conversation_id=conversation.id))

    new_participant = Participant(user_id=g.user.id, conversation_id=conversation.id, role='member')
    db.session.add(new_participant)
    db.session.commit()

    flash('You have successfully joined the group!', 'success')
    return redirect(url_for('message_thread', conversation_id=conversation.id))


@app.route('/chat/group/<int:conversation_id>/add_members', methods=['GET', 'POST'])
@login_required
def add_members(conversation_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not participant or participant.role != 'admin':
        return "You are not an admin of this group.", 403

    if request.method == 'POST':
        users_to_add = request.form.getlist('users')
        for user_id in users_to_add:
            user = db.get_or_404(User, user_id)
            existing_participant = next((p for p in conversation.participants if p.user_id == user.id), None)
            if not existing_participant:
                new_participant = Participant(user_id=user.id, conversation_id=conversation.id)
                db.session.add(new_participant)
        db.session.commit()
        flash('Members added successfully.', 'success')
        return redirect(url_for('group_info', conversation_id=conversation.id))

    existing_member_ids = [p.user_id for p in conversation.participants]
    users = User.query.filter(User.id.notin_(existing_member_ids)).all()
    return render_template('add_members.html', conversation=conversation, users=users)

@app.route('/chat/group/<int:conversation_id>/remove_member/<int:user_id>', methods=['POST'])
@login_required
def remove_member(conversation_id, user_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    admin_participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not admin_participant or admin_participant.role != 'admin':
        return "You are not an admin of this group.", 403

    member_to_remove = next((p for p in conversation.participants if p.user_id == user_id), None)
    if member_to_remove:
        db.session.delete(member_to_remove)
        db.session.commit()
        flash('Member removed successfully.', 'success')
    else:
        flash('Member not found in this group.', 'error')

    return redirect(url_for('group_info', conversation_id=conversation.id))

@app.route('/chat/group/<int:conversation_id>/update_role/<int:user_id>', methods=['POST'])
@login_required
def update_role(conversation_id, user_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    admin_participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not admin_participant or admin_participant.role != 'admin':
        return "You are not an admin of this group.", 403

    member_to_update = next((p for p in conversation.participants if p.user_id == user_id), None)
    if member_to_update:
        new_role = request.form.get('role')
        if new_role in ['admin', 'member']:
            member_to_update.role = new_role
            db.session.commit()
            flash('Member role updated successfully.', 'success')
        else:
            flash('Invalid role specified.', 'error')
    else:
        flash('Member not found in this group.', 'error')

    return redirect(url_for('group_info', conversation_id=conversation.id))

@app.route('/chat/create_group')
@login_required
def create_group():
    session.pop('group_creation_form', None)
    session['group_creation_form'] = {'members': [g.user.id]} # Creator is always a member
    return redirect(url_for('create_group_step', step=1))

@app.route('/chat/create_group/step/<int:step>', methods=['GET', 'POST'])
@login_required
def create_group_step(step):
    if 'group_creation_form' not in session:
        return redirect(url_for('create_group'))

    if request.method == 'POST':
        # --- Step 1: Name & Description ---
        if step == 1:
            name = request.form.get('name')
            if not name:
                flash('Group name is required.', 'error')
                return redirect(url_for('create_group_step', step=1))
            session['group_creation_form']['name'] = name
            session['group_creation_form']['description'] = request.form.get('description', '')
            session.modified = True
            return redirect(url_for('create_group_step', step=2))

        # --- Step 2: Photo ---
        elif step == 2:
            # Photo upload logic is optional and can be complex.
            # We will skip the backend processing for now but keep the step in the flow.
            return redirect(url_for('create_group_step', step=3))

        # --- Step 3: Add Members ---
        elif step == 3:
            member_ids = request.form.getlist('members')
            # Ensure creator is always included
            if str(g.user.id) not in member_ids:
                member_ids.append(str(g.user.id))
            session['group_creation_form']['members'] = list(set([int(mid) for mid in member_ids]))
            session.modified = True
            return redirect(url_for('create_group_step', step=4))

        # --- Step 4: Assign Admins ---
        elif step == 4:
            admin_ids = request.form.getlist('admins')
            # Ensure creator is always an admin
            if str(g.user.id) not in admin_ids:
                admin_ids.append(str(g.user.id))
            session['group_creation_form']['admins'] = list(set([int(aid) for aid in admin_ids]))
            session.modified = True
            return redirect(url_for('finish_group_creation'))

    # --- Handle GET requests ---
    template_name = f'create_group_step{step}.html'
    form_data=session.get('group_creation_form', {})

    if step == 3:
        current_members = form_data.get('members', [])
        # Show users that the current user is following
        users_to_show = g.user.followed.filter(~User.id.in_(current_members)).all()
        return render_template(template_name, users=users_to_show, form_data=form_data)
    elif step == 4:
        member_ids = form_data.get('members', [])
        members = User.query.filter(User.id.in_(member_ids)).all()
        return render_template(template_name, members=members, current_user_id=g.user.id, form_data=form_data)

    return render_template(template_name, form_data=form_data)

@app.route('/chat/create_group/finish', methods=['POST'])
@login_required
def finish_group_creation():
    form_data = session.get('group_creation_form')
    if not form_data or 'name' not in form_data:
        flash('An error occurred. Please start over.', 'error')
        return redirect(url_for('create_group'))

    try:
        # Create Conversation
        new_convo = Conversation(
            is_group=True,
            name=form_data['name'],
            description=form_data.get('description', '')
            # TODO: Add photo path handling here if implemented
        )
        db.session.add(new_convo)
        db.session.flush() # Flush to get the new_convo.id

        # Add Participants
        member_ids = form_data.get('members', [])
        admin_ids = form_data.get('admins', [])

        # Ensure creator is an admin
        if g.user.id not in admin_ids:
            admin_ids.append(g.user.id)

        for member_id in member_ids:
            role = 'admin' if member_id in admin_ids else 'member'
            participant = Participant(
                user_id=member_id,
                conversation_id=new_convo.id,
                role=role
            )
            db.session.add(participant)

        db.session.commit()
        session.pop('group_creation_form', None)
        flash('Group created successfully!', 'success')
        return redirect(url_for('message_thread', conversation_id=new_convo.id))
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while creating the group: {e}', 'error')
        return redirect(url_for('create_group'))

@app.route('/chat/<int:conversation_id>/settings/disappearing', methods=['POST'])
@login_required
def set_disappearing_timer(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)

    # In a real app, you'd have more robust role/permission checking here
    if not participant or (convo.is_group and participant.role != 'admin'):
        flash('You do not have permission to change this setting.', 'error')
        return redirect(request.referrer or url_for('home'))

    timer_seconds = request.form.get('timer', type=int)
    if timer_seconds is not None:
        convo.disappearing_timer_seconds = timer_seconds if timer_seconds > 0 else None
        db.session.commit()
        flash('Disappearing messages setting updated.', 'success')
    else:
        flash('Invalid timer value.', 'error')

    return redirect(request.referrer or url_for('message_thread', conversation_id=convo.id))


@app.route('/chat/group/<int:conversation_id>/info')
@login_required
def group_info(conversation_id):
    conversation = db.get_or_404(Conversation, conversation_id)
    participant = next((p for p in conversation.participants if p.user_id == g.user.id), None)
    if not participant or not conversation.is_group:
        return "Group not found or you're not a member.", 404
    return render_template('group_info.html', conversation=conversation)


@app.route('/chat/block/<int:user_id>')
@login_required
def block_user_in_chat(user_id):
    other_user = db.get_or_404(User, user_id)
    pending_convo_entry = None
    for p_entry in g.user.conversations:
        if p_entry.status == 'pending':
            convo = p_entry.conversation
            other_participant = next((p for p in convo.participants if p.user_id != g.user.id), None)
            if other_participant and other_participant.user_id == other_user.id:
                pending_convo_entry = p_entry
                break
    if pending_convo_entry:
        pending_convo_entry.status = 'blocked'
        db.session.commit()
        flash(f'You have blocked messages from {other_user.username}.', 'success')
    return redirect(url_for('chat_inbox'))

@app.route('/chat')
@login_required
def chat_inbox():
    # Use joinedload to eager load conversations to avoid N+1 queries
    user_participant_entries = Participant.query.options(
        joinedload(Participant.conversation).joinedload(Conversation.participants).joinedload(Participant.user)
    ).filter_by(user_id=g.user.id).all()

    active_chats = []
    message_requests = []
    archived_chats = []

    for p_entry in user_participant_entries:
        if p_entry.is_archived:
            archived_chats.append(p_entry)
        elif p_entry.status == 'active':
            active_chats.append(p_entry)
        elif p_entry.status == 'pending':
            message_requests.append(p_entry)

    # Sort active chats to show pinned chats first, then by last message time
    def get_sort_key(p_entry):
        convo = p_entry.conversation
        # Get the timestamp of the last message, or the conversation creation time as a fallback
        last_message = db.session.query(Message.created_at).filter(Message.conversation_id == convo.id).order_by(Message.created_at.desc()).first()
        last_activity = last_message[0] if last_message else convo.created_at
        return (p_entry.is_pinned, last_activity)

    active_chats.sort(key=get_sort_key, reverse=True)

    # Get a set of all user IDs involved in the conversations
    all_participant_ids = {p.user_id for p_entry in user_participant_entries for p in p_entry.conversation.participants}

    # Find which of those users have active stories
    now = datetime.now(timezone.utc)
    users_with_stories = db.session.query(Story.user_id).filter(
        Story.user_id.in_(all_participant_ids),
        Story.expires_at > now
    ).distinct().all()
    user_ids_with_stories = {user_id for user_id, in users_with_stories}

    return render_template(
        'chat_inbox.html',
        active_chats=active_chats,
        message_requests=message_requests,
        archived_chats=archived_chats,
        user_ids_with_stories=user_ids_with_stories,
        Message=Message
    )

@app.route('/reels')
@login_required
def reels():
    video_posts = Post.query.filter_by(content_type='video').order_by(Post.created_at.desc()).all()
    return render_template('reels.html', posts=video_posts)

@app.route('/modes/my')
@login_required
def my_modes():
    """Displays the modes the current user has selected."""
    user_modes = g.user.preferred_modes
    return render_template('my_modes.html', modes=user_modes)

@app.route('/modes/discover')
@login_required
def discover_modes():
    """Displays all available modes for users to browse."""
    all_modes = Mode.query.order_by(Mode.name).all()
    return render_template('discover_modes.html', modes=all_modes)

@app.route('/stories/user/<int:user_id>')
@login_required
def view_user_stories(user_id):
    now = datetime.now(timezone.utc)
    # Find the most recent, active story for this user
    latest_story = Story.query.filter(
        Story.user_id == user_id,
        Story.expires_at > now
    ).order_by(Story.created_at.desc()).first()

    if latest_story:
        return redirect(url_for('story_viewer', story_id=latest_story.id))
    else:
        # If no active story, you might want to redirect to the user's profile
        # or back to the inbox with a flash message.
        flash('This user has no active stories.', 'info')
        return redirect(request.referrer or url_for('home'))

@app.route('/story/<int:story_id>')
@login_required
def story_viewer(story_id):
    story = db.get_or_404(Story, story_id)
    # Optional: Add logic to ensure only followers can view, or that it hasn't expired.
    # For now, we'll keep it simple.
    return render_template('story_viewer.html', story=story)

@app.route('/notifications')
@login_required
def notifications():
    """Display a list of notifications for the user."""
    active_filter = request.args.get('filter', None)

    # Base query
    query = Notification.query.options(
        joinedload(Notification.sender),
        joinedload(Notification.related_post)
    ).filter_by(recipient_id=g.user.id)

    # Apply filter if one is provided
    if active_filter in ['like', 'follow']: # Add other types here as they are implemented
        query = query.filter_by(type=active_filter)

    user_notifications = query.order_by(Notification.created_at.desc()).all()

    # The logic to mark all as read is removed from here.
    # It will be handled by a separate route on a per-notification basis.
    return render_template('notifications.html', notifications=user_notifications, active_filter=active_filter)

@app.route('/post/<int:post_id>')
@login_required
def post_detail(post_id):
    """Displays a single post in detail."""
    post = db.get_or_404(Post, post_id)
    comments = post.comments.order_by(Comment.created_at.asc()).all()
    return render_template('post_detail.html', post=post, comments=comments)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    post = db.get_or_404(Post, post_id)
    comment_text = request.form.get('comment_text')

    if not comment_text:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('post_detail', post_id=post.id))

    comment = Comment(text=comment_text, user_id=g.user.id, post_id=post.id)
    db.session.add(comment)

    # Create a notification for the post author, but not if they are commenting on their own post
    if post.author.id != g.user.id:
        notification = Notification(
            recipient_id=post.author.id,
            sender_id=g.user.id,
            type='comment',
            related_id=post.id
        )
        db.session.add(notification)

    db.session.commit()

    flash('Your comment has been posted.', 'success')
    return redirect(url_for('post_detail', post_id=post.id))

@app.route('/notifications/read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_as_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.recipient_id != g.user.id:
        return {'error': 'Forbidden'}, 403

    notification.is_read = True
    db.session.commit()
    return {'success': True}, 200

@app.route('/rooms/discover')
@login_required
def discover_rooms():
    public_rooms = Conversation.query.filter_by(is_public=True).order_by(Conversation.created_at.desc()).all()
    return render_template('discover_rooms.html', rooms=public_rooms)

@app.route('/rooms/create', methods=['GET', 'POST'])
@login_required
def create_room():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description', '')
        if not name:
            flash('Room name is required.', 'error')
            return redirect(url_for('create_room'))

        new_room = Conversation(
            name=name,
            description=description,
            is_public=True,
            is_group=True # Public rooms are a form of group chat
        )
        # The creator becomes the host
        host_participant = Participant(
            user=g.user,
            conversation=new_room,
            role='host'
        )
        db.session.add(new_room)
        db.session.add(host_participant)
        db.session.commit()

        flash('Public room created successfully!', 'success')
        return redirect(url_for('view_room', room_id=new_room.id))

    return render_template('create_room.html')

@app.route('/rooms/<int:room_id>')
@login_required
def view_room(room_id):
    room = db.get_or_404(Conversation, room_id)
    if not room.is_public:
        flash('This is not a public room.', 'error')
        return redirect(url_for('discover_rooms'))

    # Check if user is a participant
    participant = next((p for p in room.participants if p.user_id == g.user.id), None)

    messages = room.messages.order_by(Message.created_at.asc()).all()

    return render_template('room_view.html', room=room, messages=messages, participant=participant)

@app.route('/rooms/join/<int:room_id>', methods=['POST'])
@login_required
def join_room(room_id):
    room = db.get_or_404(Conversation, room_id)
    if not room.is_public:
        flash('This room is not public.', 'error')
        return redirect(url_for('discover_rooms'))

    # Check if user is already a participant
    existing_participant = next((p for p in room.participants if p.user_id == g.user.id), None)
    if existing_participant:
        flash('You are already in this room.', 'info')
        return redirect(url_for('view_room', room_id=room.id))

    # Add user as a participant with the 'listener' role by default
    new_participant = Participant(
        user=g.user,
        conversation=room,
        role='listener'
    )
    db.session.add(new_participant)
    db.session.commit()

    flash('You have joined the room!', 'success')
    return redirect(url_for('view_room', room_id=room.id))

@app.route('/call/<int:conversation_id>')
@login_required
def call_view(conversation_id):
    convo = db.get_or_404(Conversation, conversation_id)
    # Ensure user is a participant
    participant = next((p for p in convo.participants if p.user_id == g.user.id), None)
    if not participant:
        return "You are not a member of this conversation.", 403

    # Get the other user in a 1-on-1 chat
    other_user = None
    if not convo.is_group:
        other_user = next((p.user for p in convo.participants if p.user_id != g.user.id), None)

    return render_template('call_view.html', conversation=convo, other_user=other_user)


# --- SOCKETIO EVENTS ---
@socketio.on('send_message')
def handle_send_message_event(data):
    user_id = session.get('user_id')
    if not user_id: return
    user = db.session.get(User, user_id)
    convo = db.get_or_404(Conversation, data['room'])

    # Check if the user is a participant by checking their ID
    participant_user_ids = {p.user_id for p in convo.participants}
    if user_id not in participant_user_ids:
        # Special check for public rooms where a non-participant might be able to join and send
        # For now, we restrict to participants
        return

    # Additional check for public rooms: only certain roles can send messages
    if convo.is_public:
        participant = next((p for p in convo.participants if p.user_id == user_id), None)
        if not participant or participant.role not in ['host', 'co-host', 'participant']:
            return # Listeners cannot send messages

    new_message = Message(conversation_id=data['room'], user_id=user_id, body=data['message'])
    db.session.add(new_message)
    db.session.commit()
    message_data = {'body': new_message.body, 'author_name': new_message.sender.full_name, 'author_username': new_message.sender.username, 'user_id': new_message.user_id, 'message_id': new_message.id}
    emit('new_message', message_data, room=data['room'])

@socketio.on('react_message')
def handle_react_message(data):
    user_id = session.get('user_id')
    if not user_id: return

    message_id = data.get('message_id')
    reaction_char = data.get('reaction')

    if not message_id or not reaction_char: return

    # Check if user has already reacted with the same emoji
    existing_reaction = MessageReaction.query.filter_by(
        message_id=message_id,
        user_id=user_id,
        reaction=reaction_char
    ).first()

    if existing_reaction:
        # User is removing their reaction
        db.session.delete(existing_reaction)
        db.session.commit()
    else:
        # User is adding a new reaction
        # Optional: Limit one reaction type per user per message
        MessageReaction.query.filter_by(message_id=message_id, user_id=user_id).delete()
        new_reaction = MessageReaction(
            message_id=message_id,
            user_id=user_id,
            reaction=reaction_char
        )
        db.session.add(new_reaction)
        db.session.commit()

    # Broadcast the change to everyone in the room
    message = db.get_or_404(Message, message_id)
    room = message.conversation_id
    # Get updated reaction counts
    reactions_summary = db.session.query(
        MessageReaction.reaction, db.func.count(MessageReaction.reaction)
    ).filter_by(message_id=message_id).group_by(MessageReaction.reaction).all()

    emit('message_reaction_update', {
        'message_id': message_id,
        'reactions': {r: c for r, c in reactions_summary}
    }, room=room)

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)

@socketio.on('leave')
def on_leave(data):
    room = data['room']
    leave_room(room)

# --- WebRTC Signaling Events ---
# In-memory store for room participants. Not suitable for production with multiple workers.
call_rooms = {}

@socketio.on('join-call-room')
def handle_join_call_room(data):
    room = data['room']
    sid = request.sid
    join_room(room)

    # Get existing users in the room
    existing_sids = call_rooms.get(room, [])

    # Send existing users to the new user
    emit('existing-peers', existing_sids, room=sid)

    # Add new user to the room's user list
    if room not in call_rooms:
        call_rooms[room] = []
    call_rooms[room].append(sid)

    # Announce the new user to all other users
    emit('new-peer', {'sid': sid}, broadcast=True, include_self=False, room=room)

@socketio.on('offer')
def handle_offer(data):
    emit('offer', {'offer': data['offer'], 'from_sid': request.sid}, room=data['to_sid'])

@socketio.on('answer')
def handle_answer(data):
    emit('answer', {'answer': data['answer'], 'from_sid': request.sid}, room=data['to_sid'])

@socketio.on('ice-candidate')
def handle_ice_candidate(data):
    emit('ice-candidate', {'candidate': data['candidate'], 'from_sid': request.sid}, room=data['to_sid'])

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    # Find which room the user was in and remove them
    room_to_leave = None
    for room, sids in call_rooms.items():
        if sid in sids:
            sids.remove(sid)
            room_to_leave = room
            break

    if room_to_leave:
        # Announce user has left
        emit('peer-left', {'sid': sid}, broadcast=True, room=room_to_leave)


if __name__ == '__main__':
    socketio.run(app, debug=True)
