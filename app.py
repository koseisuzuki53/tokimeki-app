import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random
app = Flask(__name__)

# 🔑 重要：セッション用のキーを設定
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key")




# Render / ローカル両対応
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///items.db"
).replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


# ---------------------------
# Models
# ---------------------------
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

from flask_login import UserMixin

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    items = db.relationship("Item", backref="user", lazy=True)

from flask_login import LoginManager, login_user, logout_user, login_required, current_user

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
    """テンプレート式クエスト生成（AIなし）"""

    # 未評価 → 最優先で「評価クエスト」
    if item.tokimeki is None:
        return f"『{item.name}』にときめいていますか？ときめき度を入力してみましょう。"

    # ときめき低い → 手放し促し
    if item.tokimeki <= 2:
        return random.choice(DISPOSE_TEMPLATES).format(name=item.name)

    # ときめき適正（3〜5）→ 一旦評価クエスト
    return f"{item.name} の状態を軽く見直してみましょう。"


# ---------------------------
# Routes
# ---------------------------
@app.route("/")
@login_required
def index():
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.date_added.desc()).all()


    # 1. 未評価アイテム → 最優先
    unrated_item = Item.query.filter(Item.tokimeki.is_(None)).first()
    if unrated_item:
        quest = {
            "item_id": unrated_item.id,
            "item_name": unrated_item.name,
            "quest_text": f"{unrated_item.name} のときめき度を評価してみましょう。",
            "special": False
        }
        return render_template("index.html", items=items, quest=quest)

    # 2. 全アイテムが評価済み + ときめきが十分 → 特別クエスト
    all_items = Item.query.all()
    if all_items and all(item.tokimeki and item.tokimeki >= 3 for item in all_items):
        quest = {
            "item_id": "none",
            "item_name": None,
            "quest_text": "モノが整っています！新しいアイテムを登録してみましょう。",
            "special": True
        }
        return render_template("index.html", items=items, quest=quest)

    # 3. ときめきの低い順に通常クエスト
    item = (
        Item.query.filter(Item.tokimeki.isnot(None))
        .order_by(Item.tokimeki.asc())
        .first()
    )

    if item:
        quest_text = generate_template_quest(item)
        quest = {
            "item_id": item.id,
            "item_name": item.name,
            "quest_text": quest_text,
            "special": False
        }
    else:
        quest = None

    return render_template("index.html", items=items, quest=quest)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_item():
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        features = request.form.get("features", "")

        item = Item(
            name=name,
            category=category,
            tokimeki=None,
            features=features,
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
        new_tokimeki = int(request.form["tokimeki"])
        mood = request.form.get("mood", "なし")

        item.tokimeki = new_tokimeki
        db.session.commit()

        db.session.add(ActionLog(action_type="rate", item_name=item.name, mood=mood))
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("rate_item.html", item=item)


@app.route("/delete/<int:item_id>", methods=["GET", "POST"])
@login_required
def delete_with_mood(item_id):
    item = Item.query.get_or_404(item_id)

    if request.method == "POST":
        mood = request.form.get("mood", "なし")

        db.session.add(ActionLog(action_type="delete", item_name=item.name, mood=mood))
        db.session.delete(item)
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("delete_item.html", item=item)


@app.route("/history")
@login_required
def history():
    logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).all()
    return render_template("history.html", logs=logs)


@app.route("/resolve_quest/<item_id>")
@login_required
def resolve_quest(item_id):

    # 特別クエスト ＝ 新規追加
    if item_id == "none":
        return redirect(url_for("add_item"))

    item_id = int(item_id)
    item = Item.query.get_or_404(item_id)

    # 未評価 → 評価画面へ
    if item.tokimeki is None:
        return redirect(url_for("rate_item", item_id=item.id))

    # 通常クエスト
    quest_text = generate_template_quest(item)
    dispose_keywords = ["手放", "処分", "捨て"]

    if any(k in quest_text for k in dispose_keywords):
        return redirect(url_for("delete_with_mood", item_id=item.id))

    return redirect(url_for("rate_item", item_id=item.id))

from werkzeug.security import generate_password_hash, check_password_hash

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        hashed_pw = generate_password_hash(password)

        user = User(username=username, password_hash=hashed_pw)
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
