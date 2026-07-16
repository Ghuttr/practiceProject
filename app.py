from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    request,
    session,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
# Импорты для авторизации через Google
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user

# --- Единая инициализация приложения ---
app = Flask(__name__)

# Загрузка секретов из .env
app.config.from_pyfile('config.py')

# Секретный ключ для сессий и flash-сообщений
app.config['SECRET_KEY'] = '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'

# Отключаем отслеживание модификаций для производительности
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Определяем путь к папке проекта
basedir = os.path.abspath(os.path.dirname(__file__))

# Настраиваем две разные базы данных SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "blog.db")}'
app.config['SQLALCHEMY_BINDS'] = {
    'users': f'sqlite:///{os.path.join(basedir, "users.db")}',
}

# Инициируем базу данных
db = SQLAlchemy(app)

# === НАЧАЛО: Авторизация через Google === #

# Подключение Authlib
oauth = OAuth(app)
google = oauth.register(
    name='google',
    # Эти данные берутся из config.py или .env
    client_id=app.config.get("GOOGLE_CLIENT_ID"),
    client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# Для интеграции с Flask-Login нам нужен класс пользователя
class CustomUser(UserMixin):
    def __init__(self, user_id, username=None):
        self.id = user_id
        self.username = username or f"Google_{user_id}"


# Менеджер логинов
login_manager = LoginManager()
login_manager.init_app(app)


@login_manager.user_loader
def load_user(user_id):
    return CustomUser(user_id)  # Мы просто возвращаем объект по ID, без БД


@app.route("/auth/google")
def google_auth():
    """Перенаправляет на страницу входа Google."""
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/callback")
def google_callback():
    token = oauth.google.authorize_access_token()  # Получает токен доступа
    if not token:
        flash("Ошибка аутентификации.")
        return redirect(url_for("login"))

    resp = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo', token=token)
    user_info = resp.json()

    sub = user_info["sub"]  # Уникальный ID в системе Google
    username = user_info.get("name", f"google_{sub}")
    email = user_info.get("email") or f"user_{sub}@gmail.com"  # Защита от None

    existing_user = User.query.filter_by(email=email).first()

    # Вариант А: Пользователь уже существует
    if existing_user is not None:
        login_user(CustomUser(existing_user.id, existing_user.username))
        return redirect(url_for("index"))  # Логиним существующего

    # Вариант B: Новый пользователь
    else:
        new_user = User(username=f"google_{sub}", email=email)
        new_user.set_password(sub[:8])  # Хэшируем часть суба как пароль

        try:
            db.session.add(new_user)
            db.session.commit()

            # Сразу логиним созданного пользователя
            login_user(CustomUser(new_user.id, new_user.username))
            flash(f"Пользователь {new_user.username} создан.", category="success")
            return redirect(url_for("index"))

        except Exception as e:
            flash(f"Ошибка при создании аккаунта: {e}")
            return redirect(url_for("login"))


@app.route('/logout')
def logout():
    """Выход из системы"""
    logout_user()
    session.pop('username', None)
    return redirect(url_for('posts'))


# === КОНЕЦ: Авторизация через Google === #

# --- Модели ---

class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    intro = db.Column(db.String(300), nullable=False)
    text = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return '<Article %r>' % self.id


class User(db.Model):
    __bind_key__ = 'users'  # Указываем, что эта модель использует базу 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# Создание таблиц в обеих базах данных
with app.app_context():
    db.create_all()


# --- Маршруты для блога (Articles) ---

@app.route('/')
@app.route('/home')
def index():
    articles = Article.query.order_by(Article.date.desc()).all()
    welcome_msg = ""
    if current_user.is_authenticated:
        welcome_msg = f'Привет, {current_user.username}! <a href="/logout">Выйти</a>'
    elif 'username' in session:
        welcome_msg = f'Привет, {session["username"]}! <a href="/logout">Выйти</a>'
    return render_template("posts.html", articles=articles, user_message=welcome_msg)


@app.route('/posts')
def posts():
    articles = Article.query.order_by(Article.date.desc()).all()
    return render_template("posts.html", articles=articles)


@app.route('/posts/<int:id>')
def post_detail(id):
    article = Article.query.get_or_404(id)
    return render_template("post_detail.html", article=article)


@app.route('/posts/<int:id>/del', methods=['GET', 'POST'])
def post_delete(id):
    article = Article.query.get_or_404(id)
    try:
        db.session.delete(article)
        db.session.commit()
        return redirect(url_for('posts'))
    except Exception as e:
        return f"При удалении статьи произошла ошибка: {e}"


@app.route('/posts/<int:id>/update', methods=['GET', 'POST'])
def post_update(id):
    article = Article.query.get_or_404(id)
    if request.method == "POST":
        article.title = request.form['title']
        article.intro = request.form['intro']
        article.text = request.form['text']

        try:
            db.session.commit()
            return redirect(url_for('post_detail', id=article.id))
        except Exception as e:
            return f"При редактировании статьи произошла ошибка: {e}"
    else:
        return render_template("post_update.html", article=article)


@app.route('/create-article', methods=['GET', 'POST'])
def create_article():
    if request.method == "POST":
        title = request.form['title']
        intro = request.form['intro']
        text = request.form['text']

        article = Article(title=title, intro=intro, text=text)

        try:
            db.session.add(article)
            db.session.commit()
            return redirect(url_for('posts'))
        except Exception as e:
            return f"При добавлении статьи произошла ошибка: {e}"
    else:
        return render_template("create_article.html")


# --- Маршруты для авторизации (Users) ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        # Проверяем на уникальность
        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash('Пользователь с таким именем или почтой уже существует.')
            return redirect(url_for('register'))

        new_user = User(username=username, email=email)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        flash('Регистрация успешна!')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Сначала пробуем найти по имени пользователя
        user = User.query.filter_by(username=username).first()

        # Если не нашли, пытаемся найти по почте (для тех, кто зашёл через Google)
        if not user:
            user = User.query.filter_by(email=username).first()

        if user and user.check_password(password):
            # Используем либо старый способ сессии, либо новый через Flask-Login
            session['username'] = user.username
            login_user(CustomUser(user.id, user.username))
            return redirect(url_for('posts'))  # Перенаправляем на главную после входа
        else:
            flash('Неверное имя пользователя или пароль.', category="danger")
            return redirect(url_for('login'))

    return render_template('login.html')


if __name__ == "__main__":
    app.run(debug=True)