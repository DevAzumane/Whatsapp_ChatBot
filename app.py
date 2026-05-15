# =========================================================
# MEDIASSIST AI - META WHATSAPP CLOUD API VERSION
# =========================================================

from flask import Flask, request, jsonify
import os
import json
import uuid
import requests
import pandas as pd

from pathlib import Path
from datetime import datetime
from rapidfuzz import fuzz

app = Flask(__name__)

# =========================================================
# PATHS
# =========================================================

DATA_DIR = Path("data")

INVENTORY_FILE_CSV = DATA_DIR / "inventory.csv"
INVENTORY_FILE_XLSX = DATA_DIR / "inventory.xlsx"

REQUESTS_EXCEL_FILE = DATA_DIR / "customer_requests.xlsx"
SESSION_FILE = DATA_DIR / "customer_sessions.json"

# =========================================================
# META WHATSAPP CONFIG
# =========================================================

VERIFY_TOKEN = "Mediassist"

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")

PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")

META_API_URL = (
    f"https://graph.facebook.com/v22.0/"
    f"{PHONE_NUMBER_ID}/messages"
)

# =========================================================
# CATEGORY SYNONYMS
# =========================================================

CATEGORY_SYNONYMS = {
    "Fever": ["fever", "temperature", "body heat", "paracetamol"],
    "Cold & Cough": ["cold", "cough", "running nose"],
    "Diabetes": ["diabetes", "sugar"],
    "Blood Pressure (BP)": ["bp", "blood pressure"],
    "Pain Relief": ["pain", "headache", "body pain"],
    "Baby Care": ["baby", "diaper"],
    "Skin Care": ["skin", "cream"],
    "Digestive Care": ["gas", "acidity"],
}

# =========================================================
# HELPERS
# =========================================================

def normalize_text(value):

    return str(value).lower().strip()


def clean_column_name(col):

    return (
        str(col)
        .replace("\ufeff", "")
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
    )


def format_price(value):

    try:

        value = float(value)

        if value.is_integer():
            return str(int(value))

        return str(value)

    except Exception:

        return str(value)

# =========================================================
# INVENTORY
# =========================================================

def load_inventory():

    if INVENTORY_FILE_XLSX.exists():

        df = pd.read_excel(INVENTORY_FILE_XLSX)

    elif INVENTORY_FILE_CSV.exists():

        df = pd.read_csv(
            INVENTORY_FILE_CSV,
            sep=None,
            engine="python"
        )

    else:

        return pd.DataFrame(columns=[
            "category",
            "product_name",
            "brand",
            "variant",
            "price",
            "available_quantity",
            "prescription_required",
            "status"
        ])

    df.columns = [clean_column_name(c) for c in df.columns]

    rename_map = {
        "product": "product_name",
        "medicine": "product_name",
        "medicine_name": "product_name",
        "quantity": "available_quantity",
        "stock": "available_quantity",
        "qty": "available_quantity",
        "available_stock": "available_quantity",
        "prescription": "prescription_required",
    }

    df = df.rename(columns=rename_map)

    required_cols = [
        "category",
        "product_name",
        "brand",
        "variant",
        "price",
        "available_quantity",
        "prescription_required"
    ]

    for col in required_cols:

        if col not in df.columns:
            df[col] = ""

    df["available_quantity"] = (
        pd.to_numeric(
            df["available_quantity"],
            errors="coerce"
        )
        .fillna(0)
        .astype(int)
    )

    df["price"] = (
        pd.to_numeric(
            df["price"],
            errors="coerce"
        )
        .fillna(0)
    )

    df["status"] = df["available_quantity"].apply(
        lambda x: "available" if x > 0 else "out_of_stock"
    )

    return df

# =========================================================
# SESSIONS
# =========================================================

def load_sessions():

    if not SESSION_FILE.exists():
        return {}

    try:

        with open(
            SESSION_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_sessions(sessions):

    DATA_DIR.mkdir(exist_ok=True)

    with open(
        SESSION_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(sessions, f, indent=2)


def set_customer_session(phone, data):

    sessions = load_sessions()

    sessions[phone] = data

    save_sessions(sessions)


def get_customer_session(phone):

    sessions = load_sessions()

    return sessions.get(phone, {})

# =========================================================
# SEARCH ENGINE
# =========================================================

def detect_category(text):

    text = normalize_text(text)

    for category, keywords in CATEGORY_SYNONYMS.items():

        if normalize_text(category) in text:
            return category

        for keyword in keywords:

            if normalize_text(keyword) in text:
                return category

    return None


def get_products_by_category(category, limit=10):

    df = load_inventory()

    category_norm = normalize_text(category)

    matched = df[
        df["category"].apply(
            lambda x: category_norm in normalize_text(x)
        )
    ]

    return matched.head(limit).to_dict(orient="records")


def search_direct_product(query, limit=6):

    df = load_inventory()

    if df.empty:
        return []

    query_text = normalize_text(query)

    results = []

    for _, row in df.iterrows():

        searchable_text = " ".join([
            str(row.get("product_name", "")),
            str(row.get("brand", "")),
            str(row.get("variant", "")),
            str(row.get("category", ""))
        ]).lower()

        score = fuzz.token_set_ratio(
            query_text,
            searchable_text
        )

        if score >= 60:

            item = row.to_dict()

            item["match_score"] = score

            results.append(item)

    return sorted(
        results,
        key=lambda x: x["match_score"],
        reverse=True
    )[:limit]

# =========================================================
# PRODUCT HELPERS
# =========================================================

def get_product_quantity(product):

    qty = product.get(
        "available_quantity",
        0
    )

    try:

        return int(float(qty))

    except Exception:

        return 0


def product_is_available(product):

    return get_product_quantity(product) > 0

# =========================================================
# PRODUCT DETAIL
# =========================================================

def format_product_details(product):

    qty = get_product_quantity(product)

    available = qty > 0

    status = (
        "🟢 Available"
        if available else
        "🔴 Out of Stock"
    )

    prescription = product.get(
        "prescription_required",
        "No"
    )

    message = (
        f"💊 {product.get('product_name','')}\n\n"

        f"🏷 Brand: {product.get('brand','Generic')}\n"
        f"⚡ Variant: {product.get('variant','-')}\n"
        f"💰 Price: ₹{format_price(product.get('price',0))}\n"
        f"📦 Status: {status}\n"
        f"📋 Prescription: {prescription}"
    )

    return message

# =========================================================
# SAVE CUSTOMER REQUEST
# =========================================================

def save_customer_request(
    customer_phone,
    product,
    requested_quantity=1
):

    REQUESTS_EXCEL_FILE.parent.mkdir(exist_ok=True)

    new_row = {

        "request_id": str(uuid.uuid4())[:8],

        "customer_phone": customer_phone,

        "product_name": product.get("product_name", ""),

        "category": product.get("category", ""),

        "brand": product.get("brand", ""),

        "variant": product.get("variant", ""),

        "price": product.get("price", ""),

        "requested_quantity": requested_quantity,

        "requested_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),

        "status": "Requested"
    }

    if REQUESTS_EXCEL_FILE.exists():

        df = pd.read_excel(
            REQUESTS_EXCEL_FILE
        )

        df = pd.concat(
            [df, pd.DataFrame([new_row])],
            ignore_index=True
        )

    else:

        df = pd.DataFrame([new_row])

    df.to_excel(
        REQUESTS_EXCEL_FILE,
        index=False
    )

# =========================================================
# BOT ENGINE
# =========================================================

def get_welcome_message():

    return (
        "👋 Welcome to MediAssist AI\n\n"

        "Search medicines instantly.\n"
        "Check stock availability.\n"
        "Raise medicine requests.\n\n"

        "Try:\n"
        "• Dolo 650\n"
        "• Fever medicine\n"
        "• BP tablets"
    )


def get_bot_response(customer_phone, user_text):

    text = user_text.strip()

    text_lower = normalize_text(text)

    session = get_customer_session(customer_phone)

    # =====================================================
    # PRODUCT SELECTION
    # =====================================================

    if (
        session.get("flow") == "product_selection"
        and text.isdigit()
    ):

        index = int(text) - 1

        products = session.get("products", [])

        if 0 <= index < len(products):

            product = products[index]

            set_customer_session(customer_phone, {

                "flow": "selected_product",

                "product": product,

                "products": products
            })

            return {
                "type": "product_detail",
                "message": format_product_details(product),
                "product": product,
                "available": product_is_available(product)
            }

    # =====================================================
    # REQUEST FLOW
    # =====================================================

    if session.get("flow") == "selected_product":

        product = session.get("product")

        if text_lower in [
            "request",
            "yes"
        ]:

            if product and not product_is_available(product):

                set_customer_session(customer_phone, {

                    "flow": "awaiting_request_quantity",

                    "product": product
                })

                return {
                    "type": "text",

                    "message": (
                        f"📦 Enter quantity needed for "
                        f"{product.get('product_name', '')}"
                    )
                }

    # =====================================================
    # REQUEST QUANTITY
    # =====================================================

    if session.get("flow") == "awaiting_request_quantity":

        product = session.get("product")

        if not text.isdigit():

            return {
                "type": "text",
                "message": "❌ Please enter valid quantity."
            }

        requested_quantity = int(text)

        save_customer_request(
            customer_phone=customer_phone,
            product=product,
            requested_quantity=requested_quantity
        )

        set_customer_session(customer_phone, {})

        return {
            "type": "text",
            "message": (
                f"✅ Request submitted successfully\n\n"
                f"💊 Product: "
                f"{product.get('product_name', '')}\n"
                f"📦 Quantity: "
                f"{requested_quantity}"
            )
        }

    # =====================================================
    # GREETING
    # =====================================================

    if text_lower in [
        "hi",
        "hello",
        "hey",
        "start"
    ]:

        return {
            "type": "text",
            "message": get_welcome_message()
        }

    # =====================================================
    # CATEGORY SEARCH
    # =====================================================

    category = detect_category(text)

    if category:

        products = get_products_by_category(category)

        if products:

            set_customer_session(customer_phone, {

                "flow": "product_selection",

                "products": products
            })

            return {
                "type": "product_options",
                "products": products
            }

    # =====================================================
    # DIRECT SEARCH
    # =====================================================

    matches = search_direct_product(text)

    if matches:

        set_customer_session(customer_phone, {

            "flow": "product_selection",

            "products": matches
        })

        return {
            "type": "product_options",
            "products": matches
        }

    return {
        "type": "text",
        "message": (
            f"❌ No products found for '{text}'."
        )
    }

# =========================================================
# SEND TEXT MESSAGE
# =========================================================

def send_whatsapp_message(to, text):

    headers = {

        "Authorization": f"Bearer {WHATSAPP_TOKEN}",

        "Content-Type": "application/json"
    }

    payload = {

        "messaging_product": "whatsapp",

        "to": to,

        "type": "text",

        "text": {
            "body": text
        }
    }

    response = requests.post(
        META_API_URL,
        headers=headers,
        json=payload
    )

    print(response.text)

# =========================================================
# SEND BUTTON MESSAGE
# =========================================================

def send_button_message(to, body_text, buttons):

    headers = {

        "Authorization": f"Bearer {WHATSAPP_TOKEN}",

        "Content-Type": "application/json"
    }

    button_data = []

    for btn in buttons:

        button_data.append({

            "type": "reply",

            "reply": {

                "id": btn["id"],

                "title": btn["title"]
            }
        })

    payload = {

        "messaging_product": "whatsapp",

        "to": to,

        "type": "interactive",

        "interactive": {

            "type": "button",

            "body": {
                "text": body_text
            },

            "action": {
                "buttons": button_data
            }
        }
    }

    response = requests.post(
        META_API_URL,
        headers=headers,
        json=payload
    )

    print(response.text)

# =========================================================
# WEBHOOK VERIFY
# =========================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():

    mode = request.args.get("hub.mode")

    token = request.args.get("hub.verify_token")

    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:

        return challenge, 200

    return "Verification failed", 403

# =========================================================
# WHATSAPP WEBHOOK
# =========================================================

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():

    data = request.get_json()

    try:

        entry = data["entry"][0]

        changes = entry["changes"][0]

        value = changes["value"]

        messages = value.get("messages")

        if not messages:

            return "ok", 200

        message = messages[0]

        customer_phone = message["from"]

        # =================================================
        # BUTTON REPLY
        # =================================================

        if message["type"] == "interactive":

            incoming_msg = (
                message["interactive"]
                ["button_reply"]
                ["id"]
            )

        else:

            incoming_msg = (
                message.get("text", {})
                .get("body", "")
            )

        print("MESSAGE:", incoming_msg)

        response_data = get_bot_response(
            customer_phone,
            incoming_msg
        )

        # =================================================
        # PRODUCT OPTIONS
        # =================================================

        if response_data["type"] == "product_options":

            products = response_data["products"][:3]

            body = "📦 Matching Products\n\n"

            buttons = []

            for i, product in enumerate(products):

                body += (
                    f"{i+1}. "
                    f"{product['product_name']}\n"
                )

                buttons.append({

                    "id": str(i + 1),

                    "title": str(i + 1)
                })

            send_button_message(
                customer_phone,
                body,
                buttons
            )

        # =================================================
        # PRODUCT DETAIL
        # =================================================

        elif response_data["type"] == "product_detail":

            text = response_data["message"]

            if not response_data.get(
                "available",
                True
            ):

                send_button_message(
                    customer_phone,
                    text,
                    [
                        {
                            "id": "request",
                            "title": "Request"
                        }
                    ]
                )

            else:

                send_whatsapp_message(
                    customer_phone,
                    text
                )

        # =================================================
        # NORMAL TEXT
        # =================================================

        else:

            send_whatsapp_message(
                customer_phone,
                response_data["message"]
            )

    except Exception as e:

        print("WEBHOOK ERROR:", e)

    return "ok", 200

# =========================================================
# DEBUG
# =========================================================

@app.route("/")
def home():

    return "💊 MediAssist AI (Meta Cloud API Running)"

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(os.getenv("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )