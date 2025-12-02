import os
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import random

app = Flask(__name__)

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
    tokimeki = db.Column(db.Integer)       # None = 未評価
    features = db.Column(db.String(200))
    image_path = db.Column(db.String(200))
    date_added = db.Column(db.DateTime, default=datetime.utcnow)


class ActionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(50))  # rate / delete
    item_name = db.Column(db.String(100))
    mood = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


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
def index():
    items = Item.query.order_by(Item.date_added.desc()).all()

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
def add_item():
    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        features = request.form.get("features", "")

        item = Item(
            name=name,
            category=category,
            tokimeki=None,
            features=features
        )
        db.session.add(item)
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("add_item.html")


@app.route("/rate/<int:item_id>", methods=["GET", "POST"])
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
def history():
    logs = ActionLog.query.order_by(ActionLog.timestamp.desc()).all()
    return render_template("history.html", logs=logs)


@app.route("/resolve_quest/<item_id>")
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


if __name__ == "__main__":
    app.run(debug=True)
