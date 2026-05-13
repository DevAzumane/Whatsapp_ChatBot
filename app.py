from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    abort,
    Response
)

from rapidfuzz import fuzz
from twilio.twiml.messaging_response import MessagingResponse

import pandas as pd
from pathlib import Path
from datetime import datetime
import uuid
import os


app = Flask(__name__)

# =========================================================
# CONFIG
# =========================================================

DATA_DIR = Path("data")
INVENTORY_FILE = DATA_DIR / "inventory.csv"
REQUESTS_FILE = DATA_DIR / "requests.csv"

ADMIN_KEY = os.getenv("ADMIN_KEY", "shopbot123")


# =========================================================
# FILE HELPERS
# =========================================================


def load_inventory():

    if not INVENTORY_FILE.exists():

        return pd.DataFrame(columns=[
            "shop_id",
            "shop_name",
            "shop_type",
            "product_name",
            "category",
            "brand",
            "variant",
            "price",
            "quantity",
            "status"
        ])

    df = pd.read_csv(INVENTORY_FILE)

    df["quantity"] = (
        pd.to_numeric(df["quantity"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    df["price"] = (
        pd.to_numeric(df["price"], errors="coerce")
        .fillna(0)
    )

    return df



def save_inventory(df):

    DATA_DIR.mkdir(exist_ok=True)

    df.to_csv(INVENTORY_FILE, index=False)



def load_requests():

    if not REQUESTS_FILE.exists():

        return pd.DataFrame(columns=[
            "request_id",
            "customer_phone",
            "shop_id",
            "requested_product",
            "created_at",
            "status"
        ])

    return pd.read_csv(REQUESTS_FILE)



def save_requests(df):

    DATA_DIR.mkdir(exist_ok=True)

    df.to_csv(REQUESTS_FILE, index=False)


# =========================================================
# SEARCH ENGINE
# =========================================================


def search_products(query, shop_type=None, limit=8):

    df = load_inventory()

    if shop_type and shop_type != "All":

        df = df[
            df["shop_type"].str.lower() == shop_type.lower()
        ]

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
            str(row.get("shop_type", ""))
        ]).lower()

        score = fuzz.token_set_ratio(
            query_text,
            searchable_text
        )

        if score >= 45:

            result = row.to_dict()
            result["match_score"] = score

            results.append(result)

    results = sorted(
        results,
        key=lambda x: x["match_score"],
        reverse=True
    )

    return results[:limit]


# =========================================================
# PREMIUM MESSAGE FORMATTER
# =========================================================


def format_product_response(results):

    if not results:
        return (
            "━━━━━━━━━━━━━━━\n"
            "❌ PRODUCT NOT FOUND\n"
            "━━━━━━━━━━━━━━━\n\n"
            "Try another keyword."
        )
    top = results[0]

    message = (
        "━━━━━━━━━━━━━━━\n"
        "🛍 SHOPBOT AI\n"
        "━━━━━━━━━━━━━━━\n\n"
        "✅ PRODUCT FOUND\n\n"
        f"📦 {top['product_name']}\n"
        f"🏪 {top['shop_name']}\n"
        f"🧾 {top['category']}\n"
        f"🏷 {top['brand']}\n"
        f"📌 {top['variant']}\n"
        f"💰 Rs.{top['price']}\n"
        f"📦 Stock: {top['quantity']}\n\n"
    )

    alternatives = results[1:4]

    if alternatives:

        message += (
            "━━━━━━━━━━━━━━━"
            "🔄 MORE OPTIONS"
            "━━━━━━━━━━━━━━━"
        )

        for idx, item in enumerate(alternatives, start=1):

            message += (
                f"\n{idx}️⃣ {item['product_name']}"
                f"\n💰 Rs.{item['price']}"
                f"\n🏪 {item['shop_name']}\n"
            )

    return message


# =========================================================
# WHATSAPP MESSAGE PROCESSOR
# =========================================================


def process_message(message, customer_phone):

    text = message.strip().lower()

    # ----------------------------------
    # GREETING
    # ----------------------------------

    if text in ["hi", "hello", "hey", "start"]:

        return (
            "━━━━━━━━━━━━━━━\n"
            "🤖 WELCOME TO SHOPBOT\n"
            "━━━━━━━━━━━━━━━\n\n"

            "🔍 Search products instantly\n"
            "🛒 Find nearby shop inventory\n"
            "⚡ Fast AI product matching\n\n"

            "📌 Example Searches:\n"
            "• iphone 15\n"
            "• samsung tv\n"
            "• airpods\n"
            "• milk powder\n\n"

            "📚 Type *help* for commands"
        )

    # ----------------------------------
    # HELP
    # ----------------------------------

    if text == "help":

        return (
            "━━━━━━━━━━━━━━━\n"
            "📚 HELP MENU\n"
            "━━━━━━━━━━━━━━━\n\n"

            "🔍 Search Product\n"
            "Send any product name\n\n"

            "📝 Request Product\n"
            "request:iphone 15\n\n"

            "📦 Examples:\n"
            "• iphone\n"
            "• dairy milk\n"
            "• earbuds"
        )

    # ----------------------------------
    # PRODUCT REQUEST
    # ----------------------------------

    if text.startswith("request:"):

        product = text.replace(
            "request:",
            ""
        ).strip()

        if not product:
            return "⚠ Please enter product name"

        requests_df = load_requests()

        new_row = {
            "request_id": str(uuid.uuid4())[:8],
            "customer_phone": customer_phone,
            "shop_id": "",
            "requested_product": product,
            "created_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "status": "submitted"
        }

        requests_df = pd.concat(
            [requests_df, pd.DataFrame([new_row])],
            ignore_index=True
        )

        save_requests(requests_df)

        return (
            "━━━━━━━━━━━━━━━"
            "✅ REQUEST SUBMITTED"
            "━━━━━━━━━━━━━━━"
            f"📦 Product: {product}"
            "Our team will contact you shortly."
        )

    # ----------------------------------
    # NORMAL SEARCH
    # ----------------------------------

    results = search_products(text)

    return format_product_response(results)


# =========================================================
# SECURITY
# =========================================================


@app.before_request
def protect_admin():

    if request.path.startswith("/admin"):

        key = request.args.get("key")

        if key != ADMIN_KEY:
            abort(403)


# =========================================================
# WEBSITE ROUTES
# =========================================================


@app.route("/")
def home():

    df = load_inventory()

    shop_types = (
        ["All"] +
        sorted(df["shop_type"].dropna().unique().tolist())
        if not df.empty else ["All"]
    )

    return render_template(
        "index.html",
        shop_types=shop_types
    )


@app.route("/search", methods=["POST"])
def search():

    query = request.form.get("query", "")

    shop_type = request.form.get(
        "shop_type",
        "All"
    )

    results = search_products(query, shop_type)

    response = format_product_response(results)

    df = load_inventory()

    shop_types = (
        ["All"] +
        sorted(df["shop_type"].dropna().unique().tolist())
        if not df.empty else ["All"]
    )

    return render_template(
        "index.html",
        query=query,
        selected_shop_type=shop_type,
        response=response,
        shop_types=shop_types
    )


# =========================================================
# JSON API
# =========================================================


@app.route("/api/chat", methods=["POST"])
def api_chat():

    data = request.get_json(force=True)

    query = data.get("message", "")

    results = search_products(query)

    response = format_product_response(results)

    return jsonify({
        "reply": response,
        "results": results
    })


# =========================================================
# ADMIN PANEL
# =========================================================


@app.route("/admin")
def admin():

    inventory = load_inventory().to_dict(
        orient="records"
    )

    requests_data = (
        load_requests()
        .sort_values("created_at", ascending=False)
        .to_dict(orient="records")
    )

    return render_template(
        "admin.html",
        inventory=inventory,
        requests_data=requests_data
    )


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

    df = pd.concat(
        [df, pd.DataFrame([new_product])],
        ignore_index=True
    )

    save_inventory(df)

    return redirect(url_for("admin"))


@app.route("/admin/upload", methods=["POST"])
def upload_inventory():

    file = request.files.get("inventory_file")

    if not file:
        return redirect(url_for("admin"))

    df = pd.read_csv(file)

    required_cols = [
        "shop_id",
        "shop_name",
        "shop_type",
        "product_name",
        "category",
        "brand",
        "variant",
        "price",
        "quantity",
        "status"
    ]

    missing = [
        col for col in required_cols
        if col not in df.columns
    ]

    if missing:
        return f"Missing columns: {missing}", 400

    save_inventory(df)

    return redirect(url_for("admin"))


# =========================================================
# WHATSAPP WEBHOOK
# =========================================================


@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():

    incoming_msg = request.form.get(
        "Body",
        ""
    ).strip()

    customer_phone = request.form.get(
        "From",
        ""
    )

    reply_text = process_message(
        incoming_msg,
        customer_phone
    )

    resp = MessagingResponse()

    resp.message(reply_text)

    return Response(
        str(resp),
        mimetype="application/xml"
    )


# =========================================================
# APP START
# =========================================================


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )