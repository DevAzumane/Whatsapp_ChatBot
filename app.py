from flask import Flask, request
import os
import json
import uuid
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime
from rapidfuzz import fuzz

app = Flask(__name__)

DATA_DIR = Path("data")
INVENTORY_FILE = DATA_DIR / "inventory.csv"
REQUESTS_EXCEL_FILE = DATA_DIR / "customer_requests.xlsx"
SESSION_FILE = DATA_DIR / "customer_sessions.json"

CATEGORY_SYNONYMS = {
    "Fever": ["fever", "temperature", "body heat", "paracetamol"],
    "Cold & Cough": ["cold", "cough", "running nose", "sore throat", "throat pain", "cold syrup"],
    "Diabetes": ["sugar", "diabetes", "blood sugar", "sugar tablet"],
    "Blood Pressure (BP)": ["bp", "blood pressure", "hypertension", "bp medicine"],
    "Antibiotics": ["antibiotic", "infection"],
    "Pain Relief": ["pain", "body pain", "headache", "back pain", "pain killer"],
    "Vitamins & Supplements": ["vitamin", "supplement", "energy", "weakness"],
    "Baby Care": ["baby", "diaper", "baby powder", "baby lotion"],
    "Skin Care": ["skin", "cream", "rash", "face wash"],
    "Ayurvedic": ["ayurvedic", "herbal", "chyawanprash"],
    "Surgical & Medical Equipment": ["surgical", "gloves", "bp monitor", "wheelchair"],
    "Protein & Nutrition Supplements": ["protein", "nutrition", "health powder"],
    "Personal Care": ["personal care", "soap", "shampoo", "lotion"],
    "OTC Medicines": ["otc", "eno", "digene", "acidity", "gas"],
    "Allergy": ["allergy", "sneezing", "itching"],
    "Digestive Care": ["digestion", "stomach", "gas", "acidity"],
    "Eye Care": ["eye", "eye drops"],
    "Ear Care": ["ear", "ear drops"],
    "Dental Care": ["toothpaste", "mouthwash", "dental"],
    "First Aid": ["first aid", "bandage", "cotton", "dettol"],
    "Respiratory Care": ["asthma", "inhaler", "breathing", "nebulizer"],
    "Medical Devices": ["thermometer", "oximeter", "bp machine"],
    "Masks & PPE": ["mask", "ppe", "n95"],
    "Glucose Monitoring": ["glucometer", "glucose strip", "sugar testing"],
}


def load_inventory():
    if not INVENTORY_FILE.exists():
        return pd.DataFrame(columns=[
            "shop_id", "shop_name", "shop_type", "product_name", "category",
            "brand", "variant", "price", "quantity", "status", "prescription_required"
        ])

    df = pd.read_csv(INVENTORY_FILE)

    required_cols = [
        "shop_id", "shop_name", "shop_type", "product_name", "category",
        "brand", "variant", "price", "quantity", "status"
    ]

    for col in required_cols:
        if col not in df.columns:
            df[col] = ""

    if "prescription_required" not in df.columns:
        df["prescription_required"] = "No"

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0)

    return df


def load_sessions():
    if not SESSION_FILE.exists():
        return {}

    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_sessions(sessions):
    DATA_DIR.mkdir(exist_ok=True)

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2)


def set_customer_session(phone, session_data):
    sessions = load_sessions()
    sessions[phone] = session_data
    save_sessions(sessions)


def get_customer_session(phone):
    sessions = load_sessions()
    return sessions.get(phone, {})


def normalize_text(value):
    return str(value).lower().strip()


def detect_category(user_text):
    text = normalize_text(user_text)

    for category, keywords in CATEGORY_SYNONYMS.items():
        for keyword in keywords:
            if normalize_text(keyword) in text:
                return category

    return None


def get_products_by_category(category, limit=10):
    df = load_inventory()
    exact_match = df[df["category"].str.lower() == category.lower()]

    if exact_match.empty:
        exact_match = df[df["category"].str.lower().str.contains(category.lower(), na=False)]

    return exact_match.head(limit).to_dict(orient="records")


def search_direct_product(query, limit=5):
    df = load_inventory()

    if df.empty or not query.strip():
        return []

    query_text = normalize_text(query)
    results = []

    for _, row in df.iterrows():
        product_text = " ".join([
            str(row.get("product_name", "")),
            str(row.get("brand", "")),
            str(row.get("variant", "")),
        ]).lower()

        score = fuzz.token_set_ratio(query_text, product_text)

        if score >= 65:
            result = row.to_dict()
            result["match_score"] = score
            results.append(result)

    return sorted(results, key=lambda x: x["match_score"], reverse=True)[:limit]


def is_direct_product_query(user_text):
    text = normalize_text(user_text)

    category_words = [
        "medicine", "medicines", "tablet", "tablets", "syrup", "products",
        "product", "category", "for", "care"
    ]

    detected_category = detect_category(text)
    direct_matches = search_direct_product(text, limit=1)

    if direct_matches:
        top_score = direct_matches[0].get("match_score", 0)
        if top_score >= 78:
            return True

    if detected_category and any(word in text for word in category_words):
        return False

    if detected_category:
        return False

    return bool(direct_matches)


def save_customer_request(customer_phone, product):
    REQUESTS_EXCEL_FILE.parent.mkdir(exist_ok=True)

    new_row = {
        "request_id": str(uuid.uuid4())[:8],
        "customer_phone": customer_phone,
        "shop_id": product.get("shop_id", ""),
        "shop_name": product.get("shop_name", ""),
        "product_name": product.get("product_name", ""),
        "category": product.get("category", ""),
        "brand": product.get("brand", ""),
        "variant": product.get("variant", ""),
        "price": product.get("price", ""),
        "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "Requested"
    }

    if REQUESTS_EXCEL_FILE.exists():
        df = pd.read_excel(REQUESTS_EXCEL_FILE)
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    else:
        df = pd.DataFrame([new_row])

    df.to_excel(REQUESTS_EXCEL_FILE, index=False)


def meta_api_url():
    phone_number_id = os.getenv("PHONE_NUMBER_ID")
    return f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"


def meta_headers():
    token = os.getenv("WHATSAPP_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


def send_whatsapp_text(to, message):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }

    res = requests.post(meta_api_url(), headers=meta_headers(), json=payload)
    print("Send text response:", res.status_code, res.text)
    return res


def send_product_list(to, category, products):
    rows = []

    for idx, product in enumerate(products[:10], start=1):
        qty = int(product.get("quantity", 0))
        status = normalize_text(product.get("status", ""))
        stock_text = "Available" if qty > 0 and status == "available" else "Out of stock"

        rows.append({
            "id": f"product_{idx}",
            "title": str(product.get("product_name", ""))[:24],
            "description": f"{product.get('brand', '')} | Rs.{product.get('price', '')} | {stock_text}"[:72]
        })

    set_customer_session(to, {
        "flow": "product_selection",
        "category": category,
        "products": products
    })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": category[:50]},
            "body": {"text": f"Please choose which {category} product you want:"},
            "footer": {"text": "Select one option"},
            "action": {
                "button": "View Products",
                "sections": [{"title": category[:24], "rows": rows}]
            }
        }
    }

    res = requests.post(meta_api_url(), headers=meta_headers(), json=payload)
    print("Send list response:", res.status_code, res.text)
    return res


def send_request_button(to, product):
    set_customer_session(to, {
        "flow": "request_product",
        "product": product
    })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    f"Sorry, {product.get('product_name', 'this product')} is currently out of stock.\n\n"
                    "Do you want to raise a request?"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": "raise_request", "title": "Raise Request"}
                    }
                ]
            }
        }
    }

    res = requests.post(meta_api_url(), headers=meta_headers(), json=payload)
    print("Send request button response:", res.status_code, res.text)
    return res


def send_product_details(to, product):
    qty = int(product.get("quantity", 0))
    status = normalize_text(product.get("status", ""))

    if qty > 0 and status == "available":
        prescription = product.get("prescription_required", "No")

        reply = (
            f"{product.get('product_name', '')} is available ✅\n\n"
            f"Shop: {product.get('shop_name', '')}\n"
            f"Category: {product.get('category', '')}\n"
            f"Brand: {product.get('brand', '')}\n"
            f"Variant: {product.get('variant', '')}\n"
            f"Price: Rs.{product.get('price', '')}\n"
            f"Stock: {product.get('quantity', '')}\n"
            f"Prescription Required: {prescription}"
        )

        send_whatsapp_text(to, reply)
    else:
        send_request_button(to, product)


def send_welcome_message(to):
    message = (
        "Hi 👋 Welcome to Local Medical Store Assistant.\n\n"
        "How can I help you today?\n\n"
        "You can search by product name or category.\n\n"
        "Examples:\n"
        "- Dolo 650\n"
        "- Crocin\n"
        "- fever medicine\n"
        "- cold syrup\n"
        "- diabetes tablets\n"
        "- BP medicine\n"
        "- baby care products"
    )

    send_whatsapp_text(to, message)


def handle_customer_text(customer_phone, user_text):
    text = user_text.strip()
    text_lower = normalize_text(text)

    if text_lower in ["hi", "hello", "hey", "start", "menu"]:
        send_welcome_message(customer_phone)
        return

    if is_direct_product_query(text):
        matches = search_direct_product(text, limit=5)

        if not matches:
            send_whatsapp_text(
                customer_phone,
                f"Sorry, I could not find '{text}'. Please try another product or category."
            )
            return

        top_score = matches[0].get("match_score", 0)

        if top_score >= 78:
            send_product_details(customer_phone, matches[0])
        else:
            send_product_list(customer_phone, "Matching Products", matches)

        return

    category = detect_category(text)

    if category:
        products = get_products_by_category(category)

        if products:
            send_product_list(customer_phone, category, products)
        else:
            send_whatsapp_text(
                customer_phone,
                f"Sorry, no products are currently available under {category}."
            )

        return

    matches = search_direct_product(text, limit=5)

    if matches:
        send_product_list(customer_phone, "Matching Products", matches)
    else:
        send_whatsapp_text(
            customer_phone,
            f"Sorry, I could not find '{text}'.\n\n"
            "Please try searching like:\n"
            "- Dolo 650\n"
            "- fever medicine\n"
            "- cold syrup\n"
            "- BP medicine"
        )


@app.route("/")
def home():
    return "Local Medical Store WhatsApp Bot is running."


@app.route("/meta-whatsapp", methods=["GET", "POST"])
def meta_whatsapp_webhook():
    if request.method == "GET":
        verify_token = os.getenv("VERIFY_TOKEN")

        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == verify_token:
            return challenge, 200

        return "Verification failed", 403

    data = request.get_json()
    print("Incoming webhook:", json.dumps(data, indent=2))

    try:
        value = data["entry"][0]["changes"][0]["value"]
        messages = value.get("messages", [])

        if not messages:
            return "OK", 200

        message = messages[0]
        customer_phone = message["from"]
        message_type = message.get("type")

        if message_type == "text":
            user_text = message["text"]["body"]
            handle_customer_text(customer_phone, user_text)
            return "OK", 200

        if message_type == "interactive":
            interactive = message["interactive"]
            session = get_customer_session(customer_phone)

            if interactive["type"] == "list_reply":
                selected_id = interactive["list_reply"]["id"]

                if selected_id.startswith("product_"):
                    index = int(selected_id.replace("product_", "")) - 1
                    products = session.get("products", [])

                    if 0 <= index < len(products):
                        product = products[index]
                        send_product_details(customer_phone, product)
                    else:
                        send_whatsapp_text(customer_phone, "Sorry, selected product was not found. Please search again.")

                return "OK", 200

            if interactive["type"] == "button_reply":
                button_id = interactive["button_reply"]["id"]

                if button_id == "raise_request":
                    product = session.get("product")

                    if product:
                        save_customer_request(customer_phone, product)

                        send_whatsapp_text(
                            customer_phone,
                            f"Your request for {product.get('product_name', '')} has been submitted ✅\n\n"
                            "The shop will review and arrange it if possible."
                        )
                    else:
                        send_whatsapp_text(
                            customer_phone,
                            "Sorry, product details were not found. Please search again."
                        )

                return "OK", 200

        send_whatsapp_text(
            customer_phone,
            "Please send a product name or category to check availability."
        )

    except Exception as e:
        print("Webhook error:", e)

    return "OK", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)