# =========================================================
# MEDIASSIST AI - WHATSAPP INTERACTIVE CHATBOT
# =========================================================

from flask import Flask, request, jsonify
import os
import json
import uuid
import pandas as pd

from pathlib import Path
from datetime import datetime
from rapidfuzz import fuzz
from twilio.rest import Client

app = Flask(__name__)

# =========================================================
# TWILIO CONFIG
# =========================================================

ACCOUNT_SID = "YOUR_TWILIO_ACCOUNT_SID"
AUTH_TOKEN = "YOUR_TWILIO_AUTH_TOKEN"

TWILIO_WHATSAPP_NUMBER = "whatsapp:+14155238886"

client = Client(
    ACCOUNT_SID,
    AUTH_TOKEN
)

# =========================================================
# PATHS
# =========================================================

DATA_DIR = Path("data")

INVENTORY_FILE_CSV = DATA_DIR / "inventory.csv"
INVENTORY_FILE_XLSX = DATA_DIR / "inventory.xlsx"

REQUESTS_EXCEL_FILE = DATA_DIR / "customer_requests.xlsx"
SESSION_FILE = DATA_DIR / "customer_sessions.json"

# =========================================================
# CATEGORY SYNONYMS
# =========================================================

CATEGORY_SYNONYMS = {
    "Fever": ["fever", "temperature", "body heat"],
    "Cold & Cough": ["cold", "cough", "running nose"],
    "Diabetes": ["diabetes", "sugar"],
    "Blood Pressure (BP)": ["bp", "blood pressure"],
    "Pain Relief": ["pain", "headache"],
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
    )


def format_price(value):

    try:
        value = float(value)

        if value.is_integer():
            return str(int(value))

        return str(value)

    except:
        return "0"


# =========================================================
# INVENTORY
# =========================================================

def load_inventory():

    if INVENTORY_FILE_XLSX.exists():
        df = pd.read_excel(INVENTORY_FILE_XLSX)

    elif INVENTORY_FILE_CSV.exists():
        df = pd.read_csv(INVENTORY_FILE_CSV)

    else:
        return pd.DataFrame()

    df.columns = [clean_column_name(c) for c in df.columns]

    rename_map = {
        "medicine": "product_name",
        "product": "product_name",
        "stock": "available_quantity",
        "qty": "available_quantity",
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

    except:
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
# SEARCH
# =========================================================

def search_direct_product(query, limit=10):

    df = load_inventory()

    query = normalize_text(query)

    results = []

    for _, row in df.iterrows():

        product_name = str(row.get("product_name", ""))

        score = fuzz.token_set_ratio(
            query,
            normalize_text(product_name)
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

    try:
        return int(product.get("available_quantity", 0))

    except:
        return 0


def product_is_available(product):

    return get_product_quantity(product) > 0


def format_product_details(product):

    qty = get_product_quantity(product)

    status = (
        "🟢 Available"
        if qty > 0 else
        "🔴 Out of Stock"
    )

    return (
        f"💊 {product.get('product_name')}\n\n"
        f"🏷 Brand: {product.get('brand')}\n"
        f"⚡ Variant: {product.get('variant')}\n"
        f"💰 Price: ₹{format_price(product.get('price'))}\n"
        f"📦 Stock: {qty}\n"
        f"📋 Status: {status}"
    )


# =========================================================
# SAVE REQUEST
# =========================================================

def save_customer_request(
    customer_phone,
    product,
    requested_quantity
):

    REQUESTS_EXCEL_FILE.parent.mkdir(exist_ok=True)

    row = {
        "request_id": str(uuid.uuid4())[:8],
        "customer_phone": customer_phone,
        "product_name": product.get("product_name"),
        "requested_quantity": requested_quantity,
        "created_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }

    if REQUESTS_EXCEL_FILE.exists():

        df = pd.read_excel(
            REQUESTS_EXCEL_FILE
        )

        df = pd.concat(
            [df, pd.DataFrame([row])],
            ignore_index=True
        )

    else:

        df = pd.DataFrame([row])

    df.to_excel(
        REQUESTS_EXCEL_FILE,
        index=False
    )


# =========================================================
# WHATSAPP SENDERS
# =========================================================

def send_text_message(to, message):

    client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        body=message
    )


def send_product_list(to, products):

    rows = []

    for product in products[:10]:

        rows.append({
            "id": product["product_name"],
            "title": product["product_name"][:24],
            "description": (
                f"₹{format_price(product['price'])}"
            )[:72]
        })

    payload = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "Select Medicine"
            },
            "action": {
                "button": "View Medicines",
                "sections": [
                    {
                        "title": "Medicines",
                        "rows": rows
                    }
                ]
            }
        }
    }

    client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        content_type="application/json",
        content=json.dumps(payload)
    )


def send_request_buttons(to):

    payload = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Do you want to raise request?"
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "request_yes",
                            "title": "Request"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "cancel",
                            "title": "Cancel"
                        }
                    }
                ]
            }
        }
    }

    client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=to,
        content_type="application/json",
        content=json.dumps(payload)
    )


# =========================================================
# BOT ENGINE
# =========================================================

def process_message(customer_phone, incoming_text):

    text = incoming_text.strip()

    text_lower = normalize_text(text)

    session = get_customer_session(customer_phone)

    # =====================================
    # GREETING
    # =====================================

    if text_lower in [
        "hi",
        "hello",
        "start",
        "menu"
    ]:

        set_customer_session(customer_phone, {})

        send_text_message(
            customer_phone,
            (
                "👋 Welcome to MediAssist AI\n\n"
                "Search medicines instantly.\n\n"
                "Example:\n"
                "• Dolo 650\n"
                "• Crocin\n"
                "• Diabetes"
            )
        )

        return

    # =====================================
    # PRODUCT SELECTION
    # =====================================

    if session.get("flow") == "product_selection":

        products = session.get("products", [])

        selected = None

        for p in products:

            if normalize_text(
                p["product_name"]
            ) == text_lower:

                selected = p
                break

        if selected:

            set_customer_session(customer_phone, {
                "flow": "selected_product",
                "product": selected
            })

            send_text_message(
                customer_phone,
                format_product_details(selected)
            )

            if not product_is_available(selected):

                send_request_buttons(
                    customer_phone
                )

            return

    # =====================================
    # REQUEST BUTTON CLICK
    # =====================================

    if text_lower in [
        "request",
        "request_yes"
    ]:

        session = get_customer_session(customer_phone)

        product = session.get("product")

        if not product:

            send_text_message(
                customer_phone,
                "No product selected."
            )

            return

        set_customer_session(customer_phone, {
            "flow": "awaiting_quantity",
            "product": product
        })

        send_text_message(
            customer_phone,
            (
                f"Enter quantity for "
                f"{product.get('product_name')}\n\n"
                "Example:\n2"
            )
        )

        return

    # =====================================
    # QUANTITY FLOW
    # =====================================

    if session.get("flow") == "awaiting_quantity":

        if not text.isdigit():

            send_text_message(
                customer_phone,
                "Please enter valid quantity."
            )

            return

        quantity = int(text)

        product = session.get("product")

        save_customer_request(
            customer_phone,
            product,
            quantity
        )

        set_customer_session(customer_phone, {})

        send_text_message(
            customer_phone,
            (
                "✅ Request submitted successfully.\n\n"
                f"💊 Product: {product.get('product_name')}\n"
                f"📦 Quantity: {quantity}"
            )
        )

        return

    # =====================================
    # PRODUCT SEARCH
    # =====================================

    matches = search_direct_product(text)

    if matches:

        set_customer_session(customer_phone, {
            "flow": "product_selection",
            "products": matches
        })

        send_product_list(
            customer_phone,
            matches
        )

        return

    # =====================================
    # NO RESULTS
    # =====================================

    send_text_message(
        customer_phone,
        (
            f"❌ No medicines found for '{text}'\n\n"
            "Try another medicine."
        )
    )


# =========================================================
# WEBHOOK
# =========================================================

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():

    customer_phone = request.form.get(
        "From",
        ""
    )

    incoming_msg = request.form.get(
        "Body",
        ""
    )

    # =====================================
    # HANDLE INTERACTIVE REPLIES
    # =====================================

    button_reply = request.form.get(
        "ButtonText"
    )

    list_reply = request.form.get(
        "ListResponse"
    )

    if button_reply:
        incoming_msg = button_reply

    if list_reply:
        incoming_msg = list_reply

    process_message(
        customer_phone,
        incoming_msg
    )

    return ("OK", 200)


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return "MediAssist AI WhatsApp Bot Running"


# =========================================================
# DEBUG
# =========================================================

@app.route("/debug-inventory")
def debug_inventory():

    df = load_inventory()

    return jsonify({
        "rows": len(df),
        "sample": df.head(5).to_dict(
            orient="records"
        )
    })


# =========================================================
# CLEAR SESSION
# =========================================================

@app.route("/clear-sessions")
def clear_sessions():

    if SESSION_FILE.exists():
        SESSION_FILE.unlink()

    return jsonify({
        "success": True
    })


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port
    )