import os
from datetime import datetime, timedelta, date
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import click
from flask.cli import with_appcontext
from functools import wraps
import humanize

app = Flask(__name__)

@app.template_filter('humanize_time')
def _jinja2_filter_humanize_time(dt):
    # dt is the stored UTC time
    # We compare it with the current UTC time
    now_utc = datetime.utcnow()
    if dt > now_utc:
        return "in the future" # should not happen
    return humanize.naturaltime(now_utc - dt)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///glooba.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('users.id'))
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

    # New profile fields
    cover_photo_path = db.Column(db.String(255), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(100), nullable=True)
    work_education = db.Column(db.String(150), nullable=True)
    country = db.Column(db.String(100), nullable=True)

    posts = db.relationship('Post', backref='author', lazy='dynamic')
    stories = db.relationship('Story', backref='author', lazy=True)
    reactions = db.relationship('Reaction', backref='user', lazy='dynamic')

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
    content_type = db.Column(db.String(10), nullable=False)  # text, photo, video
    content_path = db.Column(db.String(255), nullable=True) # for photo/video
    text = db.Column(db.Text, nullable=True) # for text
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

# --- CLI COMMANDS ---
@click.command('init-db')
@with_appcontext
def init_db_command():
    db.drop_all()
    db.create_all()
    click.echo('Initialized the database.')
app.cli.add_command(init_db_command)

# --- AUTH HELPERS & DECORATORS ---
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        g.user = db.session.get(User, user_id)

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
    # If user is already logged in, skip loading and go to home
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
    if user_to_follow == g.user:
        flash('You cannot follow yourself.', 'error')
        return redirect(url_for('home'))

    g.user.follow(user_to_follow)
    db.session.commit()
    flash(f'You are now following {user_to_follow.username}.', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/unfollow/<int:user_id>')
@login_required
def unfollow(user_id):
    user_to_unfollow = db.get_or_404(User, user_id)
    if user_to_unfollow == g.user:
        flash('You cannot unfollow yourself.', 'error')
        return redirect(url_for('home'))

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
        db.session.commit()
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
                new_user = User(
                    full_name=form_data.get('full_name'),
                    username=form_data.get('username'),
                    email=form_data.get('email'),
                    phone=form_data.get('phone'),
                    date_of_birth=dob
                )
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

    new_post = Post(
        user_id=g.user.id,
        content_type='text', # Reverted back from 'video'
        text=text_content,
        mode=mode
    )
    db.session.add(new_post)
    db.session.commit()

    flash('Your post has been created!', 'success')
    return redirect(url_for('home'))

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    stats = {
        'posts': user.posts.count(),
        'followers': user.followers.count(),
        'following': user.followed.count()
    }

    posts = user.posts.order_by(Post.created_at.desc()).all()

    return render_template('profile.html', user=user, stats=stats, posts=posts)

@app.route('/home')
@login_required
def home():
    # Get stories only from users the current user follows
    stories = Story.query.join(followers, (followers.c.followed_id == Story.user_id)).filter(followers.c.follower_id == g.user.id).order_by(Story.created_at.desc()).all()

    # Fetch all posts for the global feed, newest first
    posts = Post.query.order_by(Post.created_at.desc()).all()

    return render_template('home.html', stories=stories, posts=posts)

@app.route('/reels')
@login_required
def reels():
    # Fetch all posts that are videos, for now.
    video_posts = Post.query.filter_by(content_type='video').order_by(Post.created_at.desc()).all()
    return render_template('reels.html', posts=video_posts)

if __name__ == '__main__':
    app.run(debug=True)
