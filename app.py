from flask import Flask, render_template, request, jsonify, redirect, url_for
from rapidfuzz import fuzz
import pandas as pd
from pathlib import Path
from datetime import datetime
import uuid

app = Flask(__name__)

DATA_DIR = Path("data")
INVENTORY_FILE = DATA_DIR / "inventory.csv"
REQUESTS_FILE = DATA_DIR / "requests.csv"


def load_inventory():
    if not INVENTORY_FILE.exists():
        return pd.DataFrame(columns=[
            "shop_id", "shop_name", "shop_type", "product_name", "category",
            "brand", "variant", "price", "quantity", "status"
        ])
    df = pd.read_csv(INVENTORY_FILE)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)
    return df


def save_inventory(df):
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(INVENTORY_FILE, index=False)


def load_requests():
    if not REQUESTS_FILE.exists():
        return pd.DataFrame(columns=[
            "request_id", "customer_phone", "shop_id",
            "requested_product", "created_at", "status"
        ])
    return pd.read_csv(REQUESTS_FILE)


def save_requests(df):
    DATA_DIR.mkdir(exist_ok=True)
    df.to_csv(REQUESTS_FILE, index=False)


def build_availability_message(item):
    qty = int(item.get("quantity", 0))
    status = str(item.get("status", "")).lower()

    if qty > 0 and status == "available":
        return f"Available. Stock: {qty}. Price: Rs.{item.get('price')}."
    if qty > 0:
        return f"Limited availability. Stock: {qty}. Please confirm with shop."
    return "Currently unavailable. You can raise a request."


def search_products(query, shop_type=None, limit=8):
    df = load_inventory()

    if shop_type and shop_type != "All":
        df = df[df["shop_type"].str.lower() == shop_type.lower()]

    if df.empty or not query.strip():
        return []

    query_text = query.lower().strip()
    results = []

    for _, row in df.iterrows():
        searchable_text = " ".join([
            str(row.get("product_name", "")),
            str(row.get("category", "")),
            str(row.get("brand", "")),
            str(row.get("variant", "")),
            str(row.get("shop_name", "")),
            str(row.get("shop_type", "")),
        ]).lower()

        score = fuzz.token_set_ratio(query_text, searchable_text)

        if score >= 45:
            result = row.to_dict()
            result["match_score"] = score
            result["availability_message"] = build_availability_message(result)
            results.append(result)

    results = sorted(results, key=lambda x: x["match_score"], reverse=True)
    return results[:limit]


def generate_bot_reply(query, customer_phone="", shop_type=None):
    results = search_products(query, shop_type=shop_type)

    if not results:
        return {
            "found": False,
            "reply": (
                f"Sorry, I could not find '{query}'. "
                "You can raise a request and the shop can arrange it if possible."
            ),
            "results": []
        }

    top = results[0]
    reply = (
        f"{top['product_name']} is available at {top['shop_name']}.\n"
        f"Category: {top['category']}\n"
        f"Brand: {top['brand']}\n"
        f"Variant: {top['variant']}\n"
        f"{top['availability_message']}"
    )

    alternatives = results[1:4]
    if alternatives:
        reply += "\n\nOther matching options:\n"
        for alt in alternatives:
            reply += f"- {alt['product_name']} at {alt['shop_name']} ({alt['availability_message']})\n"

    return {"found": True, "reply": reply, "results": results}


@app.route("/")
def home():
    df = load_inventory()
    shop_types = ["All"] + sorted(df["shop_type"].dropna().unique().tolist()) if not df.empty else ["All"]
    return render_template("index.html", shop_types=shop_types)


@app.route("/search", methods=["POST"])
def search():
    query = request.form.get("query", "")
    shop_type = request.form.get("shop_type", "All")
    response = generate_bot_reply(query, shop_type=shop_type)
    df = load_inventory()
    shop_types = ["All"] + sorted(df["shop_type"].dropna().unique().tolist()) if not df.empty else ["All"]

    return render_template(
        "index.html",
        query=query,
        selected_shop_type=shop_type,
        response=response,
        shop_types=shop_types
    )


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True)
    query = data.get("message", "")
    customer_phone = data.get("customer_phone", "")
    shop_type = data.get("shop_type", None)
    response = generate_bot_reply(query, customer_phone=customer_phone, shop_type=shop_type)
    return jsonify(response)


@app.route("/request-product", methods=["POST"])
def request_product():
    requested_product = request.form.get("requested_product", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()
    shop_id = request.form.get("shop_id", "").strip()

    if not requested_product:
        return redirect(url_for("home"))

    requests_df = load_requests()
    new_row = {
        "request_id": str(uuid.uuid4())[:8],
        "customer_phone": customer_phone,
        "shop_id": shop_id,
        "requested_product": requested_product,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "submitted"
    }

    requests_df = pd.concat([requests_df, pd.DataFrame([new_row])], ignore_index=True)
    save_requests(requests_df)

    return render_template("success.html", requested_product=requested_product)


@app.route("/admin")
def admin():
    inventory = load_inventory().to_dict(orient="records")
    requests_data = load_requests().sort_values("created_at", ascending=False).to_dict(orient="records")
    return render_template("admin.html", inventory=inventory, requests_data=requests_data)


@app.route("/admin/add-product", methods=["POST"])
def add_product():
    df = load_inventory()

    new_product = {
        "shop_id": request.form.get("shop_id", "").strip(),
        "shop_name": request.form.get("shop_name", "").strip(),
        "shop_type": request.form.get("shop_type", "").strip(),
        "product_name": request.form.get("product_name", "").strip(),
        "category": request.form.get("category", "").strip(),
        "brand": request.form.get("brand", "").strip(),
        "variant": request.form.get("variant", "").strip(),
        "price": request.form.get("price", "0").strip(),
        "quantity": request.form.get("quantity", "0").strip(),
        "status": request.form.get("status", "available").strip(),
    }

    df = pd.concat([df, pd.DataFrame([new_product])], ignore_index=True)
    save_inventory(df)

    return redirect(url_for("admin"))


@app.route("/admin/upload", methods=["POST"])
def upload_inventory():
    file = request.files.get("inventory_file")

    if not file:
        return redirect(url_for("admin"))

    df = pd.read_csv(file)
    required_cols = [
        "shop_id", "shop_name", "shop_type", "product_name", "category",
        "brand", "variant", "price", "quantity", "status"
    ]

    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        return f"Missing columns: {missing}", 400

    save_inventory(df)
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(debug=True)
