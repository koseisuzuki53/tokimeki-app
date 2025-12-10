import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# 🔑 セッションキー
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key")

# Render / Local 両対応DB
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///items.db"
).replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------------------
# Models
# ---------------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    items = db.relationship("Item", backref="user", lazy=True)
    logs = db.relationship("ActionLog", backref="user", lazy=True)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    category = db.Column(db.String(50))
    tokimeki = db.Column(db.Integer)
    features = db.Column(db.String(200))
    image_path = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class ActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(50))  # rate / delete
    item_name = db.Column(db.String(100))
    mood = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    # 🔥 user_id を追加（エラーの根本原因）
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


# ---------------------------
# Login manager
# ---------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()


# ---------------------------
# クエストテンプレート
# ---------------------------
DISPOSE_TEMPLATES = [
    "{name} を見直すタイミングかもしれません。手放す候補に入れてみましょう。",
    "{name} は役割を果たしていますか？思い切って手放す判断を考えてみましょう。",
]


def generate_template_quest(item):
    if item.tokimeki is None:
        return f"『{item.name}』にときめいていますか？ときめき度を入力してみましょう。"

    if item.tokimeki <= 2:
        return random.choice(DISPOSE_TEMPLATES).format(name=item.name)

    return f"{item.name} の状態を軽く見直してみましょう。"


# ---------------------------
# Routes
# ---------------------------
@app.route("/")
@login_required
def index():
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.date_added.desc()).all()

    # 未評価アイテム
    unrated_item = Item.query.filter_by(user_id=current_user.id).filter(Item.tokimeki.is_(None)).first()
    if unrated_item:
        return render_template("index.html", items=items, quest={
            "item_id": unrated_item.id,
            "item_name": unrated_item.name,
            "quest_text": f"{unrated_item.name} のときめきを評価してみましょう。",
            "special": False
        })

    # 全アイテムが3以上 → 特別クエスト
    all_items = Item.query.filter_by(user_id=current_user.id).all()
    if all_items and all(item.tokimeki and item.tokimeki >= 3 for item in all_items):
        return render_template("index.html", items=items, quest={
            "item_id": "none",
            "item_name": None,
            "quest_text": "モノが整っています！新しいアイテムを登録してみましょう。",
            "special": True
        })

    # ときめき低い順
    item = Item.query.filter_by(user_id=current_user.id).filter(Item.tokimeki.isnot(None)).order_by(Item.tokimeki.asc()).first()
    if item:
        return render_template("index.html", items=items, quest={
            "item_id": item.id,
            "item_name": item.name,
            "quest_text": generate_template_quest(item),
            "special": False
        })

    return render_template("index.html", items=items, quest=None)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_item():
    if request.method == "POST":
        item = Item(
            name=request.form["name"],
            category=request.form["category"],
            tokimeki=None,
            features=request.form.get("features", ""),
            user_id=current_user.id
        )
        db.session.add(item)
        db.session.commit()
        return redirect(url_for("index"))

    return render_template("add_item.html")


@app.route("/rate/<int:item_id>", methods=["GET", "POST"])
@login_required
def rate_item(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == "POST":
        item.tokimeki = int(request.form["tokimeki"])
        mood = request.form.get("mood", "なし")
        db.session.commit()

        # 🔥 user_id を保存
        db.session.add(ActionLog(
            user_id=current_user.id,
            action_type="rate",
            item_name=item.name,
            mood=mood
        ))
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("rate_item.html", item=item)


@app.route("/delete/<int:item_id>", methods=["GET", "POST"])
@login_required
def delete_with_mood(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == "POST":
        mood = request.form.get("mood", "なし")

        # 🔥 user_id を保存
        db.session.add(ActionLog(
            user_id=current_user.id,
            action_type="delete",
            item_name=item.name,
            mood=mood
        ))

        db.session.delete(item)
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("delete_item.html", item=item)


@app.route('/history')
@login_required
def history():
    logs = ActionLog.query.filter_by(user_id=current_user.id).order_by(ActionLog.timestamp.desc()).all()

    rated_count = ActionLog.query.filter_by(user_id=current_user.id, action_type="rate").count()
    deleted_count = ActionLog.query.filter_by(user_id=current_user.id, action_type="delete").count()

    return render_template(
        'history.html',
        logs=logs,
        rated_count=rated_count,
        deleted_count=deleted_count
    )


@app.route("/resolve_quest/<item_id>")
@login_required
def resolve_quest(item_id):

    if item_id == "none":
        return redirect(url_for("add_item"))

    item = Item.query.get_or_404(int(item_id))

    if item.tokimeki is None:
        return redirect(url_for("rate_item", item_id=item.id))

    quest_text = generate_template_quest(item)

    # 手放し判定
    if any(key in quest_text for key in ["手放", "処分", "捨て"]):
        return redirect(url_for("delete_with_mood", item_id=item.id))

    return redirect(url_for("rate_item", item_id=item.id))


# ---------------------------
# Authentication
# ---------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User(
            username=username,
            password_hash=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
