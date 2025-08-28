import os
from datetime import datetime, timedelta, date, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import click
from flask.cli import with_appcontext
from functools import wraps
import humanize
from flask_socketio import SocketIO, emit, join_room, leave_room

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
    last_active_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

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
    status = db.Column(db.String(20), default='active', nullable=False)
    last_seen_message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    user = db.relationship('User', back_populates='conversations')
    conversation = db.relationship('Conversation', back_populates='participants')

class MessageReaction(db.Model):
    __tablename__ = 'message_reactions'
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    emoji = db.Column(db.String(50), nullable=False)
    user = db.relationship('User')
    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', 'emoji', name='_message_user_emoji_uc'),)

class Conversation(db.Model):
    __tablename__ = 'conversations'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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
    body = db.Column(db.Text, nullable=True)
    content_type = db.Column(db.String(20), nullable=False, default='text')
    content_path = db.Column(db.String(255), nullable=True)
    shared_post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    shared_post = db.relationship('Post', lazy='joined')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    sender = db.relationship('User')
    reactions = db.relationship('MessageReaction', backref='message', cascade="all, delete-orphan")

    # Self-referential relationship for message replies
    parent_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=True)
    parent = db.relationship('Message', remote_side=[id], backref='replies', lazy='joined')

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
        if g.user:
            g.user.last_active_at = datetime.now(timezone.utc)
            db.session.commit()

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

@app.context_processor
def inject_datetime():
    return {'datetime': datetime, 'timezone': timezone}

@app.context_processor
def inject_models():
    return dict(Comment=Comment)

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
    messages = convo.messages.options(
        joinedload(Message.reactions).joinedload(MessageReaction.user)
    ).order_by(Message.created_at.asc()).all()
    other_user = next((p.user for p in convo.participants if p.user_id != g.user.id), None)
    other_participant = next((p for p in convo.participants if p.user_id != g.user.id), None)
    return render_template('message_thread.html', conversation=convo, messages=messages, other_user=other_user, other_participant=other_participant)

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
    user_participant_entries = Participant.query.filter_by(user_id=g.user.id).all()
    active_chats = []
    message_requests = []
    for p_entry in user_participant_entries:
        if p_entry.status == 'active':
            active_chats.append(p_entry)
        elif p_entry.status == 'pending':
            message_requests.append(p_entry)
    return render_template('chat_inbox.html', active_chats=active_chats, message_requests=message_requests, Message=Message)

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

@app.route('/chat/message/<int:message_id>/react', methods=['POST'])
@login_required
def react_to_message(message_id):
    message = db.get_or_404(Message, message_id)
    participant = next((p for p in message.conversation.participants if p.user_id == g.user.id), None)
    if not participant:
        return {'error': 'Forbidden'}, 403

    emoji = request.json.get('emoji')
    if not emoji:
        return {'error': 'Emoji is required'}, 400

    existing_reaction = MessageReaction.query.filter_by(
        message_id=message_id,
        user_id=g.user.id,
        emoji=emoji
    ).first()

    if existing_reaction:
        db.session.delete(existing_reaction)
        db.session.commit()
        socketio.emit('reaction_removed', {
            'message_id': message_id,
            'user_id': g.user.id,
            'emoji': emoji
        }, room=str(message.conversation.id))
        return {'status': 'removed'}, 200
    else:
        new_reaction = MessageReaction(
            message_id=message_id,
            user_id=g.user.id,
            emoji=emoji
        )
        db.session.add(new_reaction)
        db.session.commit()
        socketio.emit('reaction_added', {
            'message_id': message_id,
            'user_id': g.user.id,
            'username': g.user.username,
            'emoji': emoji
        }, room=str(message.conversation.id))
        return {'status': 'added'}, 201

@app.route('/chat/conversation/<int:conversation_id>/upload_media', methods=['POST'])
@login_required
def upload_chat_media(conversation_id):
    participant = Participant.query.filter_by(user_id=g.user.id, conversation_id=conversation_id).first()
    if not participant:
        return {'error': 'Forbidden'}, 403

    if 'media_file' not in request.files:
        return {'error': 'No file part'}, 400

    file = request.files['media_file']
    if file.filename == '':
        return {'error': 'No selected file'}, 400

    if file:
        filename = secure_filename(file.filename)
        chat_media_dir = os.path.join(app.static_folder, 'chat_media')
        os.makedirs(chat_media_dir, exist_ok=True)

        unique_filename = f"{g.user.id}_{int(datetime.now(timezone.utc).timestamp())}_{filename}"
        file_path = os.path.join(chat_media_dir, unique_filename)
        file.save(file_path)

        relative_path = os.path.join('chat_media', unique_filename)

        content_type = 'photo' if file.mimetype.startswith('image/') else 'video'

        return {'success': True, 'content_path': relative_path, 'content_type': content_type}, 200

    return {'error': 'File upload failed'}, 500

@app.route('/chat/message/<int:message_id>/delete', methods=['POST'])
@login_required
def delete_message(message_id):
    message = db.get_or_404(Message, message_id)
    if message.user_id != g.user.id:
        return {'error': 'Forbidden'}, 403

    # Optional: Add a time limit for deletion
    # time_since_sent = datetime.now(timezone.utc) - message.created_at
    # if time_since_sent.total_seconds() > 300: # 5 minutes
    #     return {'error': 'Too late to delete'}, 403

    db.session.delete(message)
    db.session.commit()

    socketio.emit('message_deleted', {'message_id': message_id}, room=str(message.conversation_id))

    return {'success': True}, 200

@app.route('/chat/conversations')
@login_required
def get_conversations():
    user_participant_entries = Participant.query.filter_by(user_id=g.user.id, status='active').all()
    conversations_data = []
    for p_entry in user_participant_entries:
        convo = p_entry.conversation
        if convo.is_group:
            name = convo.name
            image = url_for('static', filename=convo.group_photo_path) if convo.group_photo_path else url_for('static', filename='img/default-avatar.png')
        else:
            other_user = next((p.user for p in convo.participants if p.user_id != g.user.id), None)
            if not other_user: continue
            name = other_user.full_name
            image = url_for('static', filename='img/default-avatar.png') # Placeholder

        conversations_data.append({
            'id': convo.id,
            'name': name,
            'image': image
        })
    return {'conversations': conversations_data}

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

    parent_id = data.get('parent_id')

    new_message = Message(
        conversation_id=data['room'],
        user_id=user_id,
        body=data.get('message'),
        parent_id=data.get('parent_id'),
        content_type=data.get('content_type', 'text'),
        content_path=data.get('content_path'),
        shared_post_id=data.get('shared_post_id')
    )
    db.session.add(new_message)
    db.session.commit()

    parent_message_data = None
    if new_message.parent:
        parent_message_data = {
            'body': new_message.parent.body,
            'author_name': new_message.parent.sender.full_name
        }

    shared_post_data = None
    if new_message.shared_post:
        shared_post_data = {
            'id': new_message.shared_post.id,
            'text': new_message.shared_post.text,
            'author_name': new_message.shared_post.author.full_name,
            'content_path': new_message.shared_post.content_path,
            'content_type': new_message.shared_post.content_type
        }

    message_data = {
        'id': new_message.id,
        'body': new_message.body,
        'author_name': new_message.sender.full_name,
        'author_username': new_message.sender.username,
        'user_id': new_message.user_id,
        'created_at': new_message.created_at.isoformat(),
        'parent': parent_message_data,
        'content_type': new_message.content_type,
        'content_path': new_message.content_path,
        'shared_post': shared_post_data
    }
    emit('new_message', message_data, room=data['room'])

@socketio.on('join')
def on_join(data):
    user_id = session.get('user_id')
    if not user_id: return
    room = data['room']
    join_room(room)
    emit('user_stopped_typing', {'user_id': user_id}, room=room, include_self=False)

@socketio.on('leave')
def on_leave(data):
    user_id = session.get('user_id')
    if not user_id: return
    room = data['room']
    leave_room(room)
    emit('user_stopped_typing', {'user_id': user_id}, room=room, include_self=False)

@socketio.on('typing_start')
def handle_typing_start(data):
    user_id = session.get('user_id')
    if not user_id: return
    user = db.session.get(User, user_id)
    if not user: return
    room = data['room']
    emit('user_typing', {'user_id': user.id, 'username': user.username}, room=room, include_self=False)

@socketio.on('typing_stop')
def handle_typing_stop(data):
    user_id = session.get('user_id')
    if not user_id: return
    room = data['room']
    emit('user_stopped_typing', {'user_id': user_id}, room=room, include_self=False)

@socketio.on('message_seen')
def handle_message_seen(data):
    user_id = session.get('user_id')
    if not user_id: return
    conversation_id = data['room']
    message_id = data['message_id']

    participant = Participant.query.filter_by(user_id=user_id, conversation_id=conversation_id).first()
    if participant:
        if not participant.last_seen_message_id or message_id > participant.last_seen_message_id:
            participant.last_seen_message_id = message_id
            db.session.commit()
            emit('message_was_seen', {'message_id': message_id, 'user_id': user_id}, room=str(conversation_id), include_self=False)

if __name__ == '__main__':
    socketio.run(app, debug=True)
