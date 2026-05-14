# =========================================================
# MEDIASSIST AI - PREMIUM MEDICAL STORE CHATBOT
# =========================================================

from flask import Flask, request, jsonify
import os
import json
import uuid
import pandas as pd

from pathlib import Path
from datetime import datetime
from rapidfuzz import fuzz
from twilio.twiml.messaging_response import MessagingResponse
from flask import Response

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
# CATEGORY SYNONYMS
# =========================================================

CATEGORY_SYNONYMS = {
    "Fever": ["fever", "temperature", "body heat", "paracetamol", "fever medicine"],
    "Cold & Cough": ["cold", "cough", "running nose", "sore throat", "cold syrup"],
    "Diabetes": ["diabetes", "sugar", "blood sugar"],
    "Blood Pressure (BP)": ["bp", "blood pressure", "hypertension"],
    "Pain Relief": ["pain", "headache", "body pain", "back pain"],
    "Baby Care": ["baby", "diaper", "baby powder"],
    "Skin Care": ["skin", "cream", "face wash"],
    "Digestive Care": ["gas", "acidity", "digestion"],
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
# PREMIUM DETAIL CARD
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
# REQUEST STORAGE
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

    session = get_customer_session(
        customer_phone
    )
    # =====================================
    # REQUEST FLOW
    # =====================================

    # User selected product and wants request

    if session.get("flow") == "selected_product":

        product = session.get("product")

        products = session.get("products", [])

        if text_lower in [
            "request",
            "raise request",
            "yes"
        ]:

            if product and not product_is_available(product):

                set_customer_session(customer_phone, {

                    "flow": "awaiting_request_quantity",

                    "product": product,

                    "products": products,

                    "category": session.get(
                        "category",
                        ""
                    )
                })

                return {
                    "type": "text",

                    "message": (
                        f"📦 Enter quantity needed for "
                        f"{product.get('product_name', '')}\n\n"

                        "Example:\n"
                        "2"
                    )
                }

    # =====================================
    # USER ENTERING REQUEST QUANTITY
    # =====================================

    if session.get("flow") == "awaiting_request_quantity":

        product = session.get("product")

        if not text.isdigit():

            return {
                "type": "text",

                "message": (
                    "❌ Please enter valid quantity.\n\n"
                    "Example:\n"
                    "2"
                )
            }

        requested_quantity = int(text)

        if requested_quantity <= 0:

            return {
                "type": "text",

                "message": (
                    "❌ Quantity must be greater than 0."
                )
            }

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

    # GREETING

    if text_lower in [
        "hi",
        "hello",
        "hey",
        "start",
        "menu"
    ]:

        return {
            "type": "text",
            "message": get_welcome_message()
        }
        

    # CATEGORY SEARCH

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
                "message": f"{category} products",
                "products": products
            }

    # DIRECT SEARCH

    matches = search_direct_product(text)

    if matches:

        if matches[0]["match_score"] >= 85:

            product = matches[0]

            set_customer_session(customer_phone, {
                "flow": "selected_product",
                "product": product
            })

            return {
                "type": "product_detail",
                "message": format_product_details(product),
                "product": product,
                "available": product_is_available(product)
            }

        set_customer_session(customer_phone, {
            "flow": "product_selection",
            "products": matches
        })

        return {
            "type": "product_options",
            "message": "Matching products",
            "products": matches
        }

    return {
        "type": "text",
        "message": (
            f"❌ No products found for '{text}'.\n\n"
            "Try another medicine name."
        )
    }


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():

    return """

<!DOCTYPE html>
<html>

<head>

    <title>MediAssist AI</title>

    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">

    <style>

        *{
            margin:0;
            padding:0;
            box-sizing:border-box;
        }

        body{
            background:#0f172a;
            font-family:'Inter',sans-serif;
            height:100vh;
            overflow:hidden;
        }

        .app{
            height:100vh;
            display:flex;
            justify-content:center;
            align-items:center;
            padding:20px;
        }

        .chat-container{
            width:100%;
            max-width:960px;
            height:94vh;
            background:white;
            border-radius:28px;
            overflow:hidden;
            display:flex;
            flex-direction:column;
            box-shadow:0 20px 60px rgba(0,0,0,0.35);
        }

        .header{
            background:linear-gradient(
                135deg,
                #0f766e,
                #14b8a6
            );

            color:white;

            padding:22px;

            display:flex;
            justify-content:space-between;
            align-items:center;
        }

        .brand{
            display:flex;
            align-items:center;
            gap:16px;
        }

        .logo{
            width:58px;
            height:58px;
            border-radius:18px;
            background:rgba(255,255,255,0.16);

            display:flex;
            align-items:center;
            justify-content:center;

            font-size:28px;
        }

        .header h1{
            font-size:22px;
            font-weight:800;
        }

        .header p{
            opacity:0.92;
            margin-top:4px;
        }

        .online{
            background:rgba(255,255,255,0.16);
            padding:10px 16px;
            border-radius:14px;
            font-size:13px;
            font-weight:700;
        }

        .chat-box{
            flex:1;
            overflow-y:auto;
            padding:24px;
            background:#f8fafc;
        }

        .message{
            margin-bottom:18px;
            max-width:78%;
        }

        .bot{
            margin-right:auto;
        }

        .user{
            margin-left:auto;
        }

        .bubble{
            padding:16px 18px;
            border-radius:22px;
            line-height:1.6;
            font-size:15px;
        }

        .bot .bubble{
            background:white;
            border-bottom-left-radius:8px;
            box-shadow:0 8px 18px rgba(0,0,0,0.06);
        }

        .user .bubble{
            background:linear-gradient(
                135deg,
                #14b8a6,
                #0f766e
            );

            color:white;

            border-bottom-right-radius:8px;
        }

        .time{
            margin-top:6px;
            font-size:11px;
            opacity:0.65;
        }

        .product-card{

            background:white;

            border:1px solid #e5e7eb;

            border-radius:18px;

            padding:16px;

            margin-top:12px;
        }

        .top-row{
            display:flex;
            justify-content:space-between;
            align-items:center;
        }

        .product-name{
            font-size:16px;
            font-weight:700;
            color:#111827;
        }

        .price{
            font-size:14px;
            font-weight:700;
            color:#0f766e;
        }

        .status{
            margin-top:10px;

            display:flex;
            justify-content:space-between;
            align-items:center;
        }

        .status-badge{

            font-size:12px;
            font-weight:700;

            padding:7px 12px;

            border-radius:999px;
        }

        .available{
            background:#dcfce7;
            color:#166534;
        }

        .out{
            background:#fee2e2;
            color:#991b1b;
        }

        .details-btn{
            border:none;

            background:#0f766e;

            color:white;

            padding:10px 14px;

            border-radius:12px;

            font-size:13px;
            font-weight:700;

            cursor:pointer;
        }

        .request-btn{

            margin-top:18px;

            width:100%;

            border:none;

            background:#dc2626;

            color:white;

            padding:14px;

            border-radius:16px;

            font-weight:700;

            cursor:pointer;
        }

        .input-area{
            background:white;
            padding:18px;
            border-top:1px solid #e5e7eb;

            display:flex;
            gap:12px;
        }

        .input-wrap{
            flex:1;
            background:#f1f5f9;
            border-radius:18px;
            padding:0 18px;
        }

        .input-wrap input{
            width:100%;
            border:none;
            outline:none;
            background:transparent;
            padding:18px 0;
            font-size:15px;
        }

        .send-btn{
            width:58px;
            height:58px;
            border:none;
            border-radius:18px;

            background:linear-gradient(
                135deg,
                #14b8a6,
                #0f766e
            );

            color:white;
            font-size:20px;
            cursor:pointer;
        }
        @media(max-width:768px){

        .chat-container{
            height:100vh;
            border-radius:0;
        }

        .message{
            max-width:92%;
        }

        .header h1{
            font-size:20px;
        }

        .product-card{
            padding:14px;
        }

    }

    </style>

</head>

<body>

<div class="app">

<div class="chat-container">

<div class="header">

    <div class="brand">

        <div class="logo">
            💊
        </div>

        <div>
            <h1>MediAssist AI</h1>
            <p>Smart Medical Store Assistant</p>
        </div>

    </div>

    <div class="online">
        ● Online
    </div>

</div>

<div id="chatBox" class="chat-box">

</div>

<div class="input-area">

    <div class="input-wrap">

        <input
            id="userInput"
            placeholder="Search medicine..."
            onkeydown="if(event.key==='Enter') sendMessage()"
        >

    </div>

    <button class="send-btn" onclick="sendMessage()">
        ➤
    </button>

</div>

</div>

</div>

<script>

const TEST_PHONE = "web_user";

function currentTime(){

    return new Date().toLocaleTimeString([],{
        hour:'2-digit',
        minute:'2-digit'
    });
}

function addMessage(text,sender){

    const box = document.getElementById("chatBox");

    const div = document.createElement("div");

    div.className = "message " + sender;

    div.innerHTML = `
        <div class="bubble">
            ${text.replaceAll("\\n","<br>")}
        </div>

        <div class="time">
            ${currentTime()}
        </div>
    `;

    box.appendChild(div);

    box.scrollTop = box.scrollHeight;
}

function renderProductOptions(products){

    const box = document.getElementById("chatBox");

    let html = "";

    products.forEach((p,index)=>{

        const qty = Number(
            p.available_quantity || 0
        );

        const available = qty > 0;

        html += `

            <div class="product-card">

                <div class="top-row">

                    <div class="product-name">
                        ${p.product_name}
                    </div>

                    <div class="price">
                        ₹${p.price || 0}
                    </div>

                </div>

                <div class="status">

                    <div class="status-badge ${available ? 'available':'out'}">

                        ${available ? 'Available':'Out of Stock'}

                    </div>

                    <button
                        class="details-btn"
                        onclick="selectProduct('${p.product_name}')"
                    >
                        Details
                    </button>

                </div>

            </div>
        `;
    });

    const div = document.createElement("div");

    div.className = "message bot";

    div.innerHTML = `
        <div class="bubble">

            <b>Matching Products</b>

            ${html}

        </div>

        <div class="time">
            ${currentTime()}
        </div>
    `;

    box.appendChild(div);

    box.scrollTop = box.scrollHeight;
}

function renderProductDetail(data){

    const box = document.getElementById("chatBox");

    let html = `
        <div>

            ${data.message.replaceAll("\\n","<br>")}

        </div>
    `;

    if(!data.available){

        html += `

            <button
                class="request-btn"
                onclick="raiseRequest()"
            >
                Request Medicine
            </button>
        `;
    }

    const div = document.createElement("div");

    div.className = "message bot";

    div.innerHTML = `
        <div class="bubble">

            ${html}

        </div>

        <div class="time">
            ${currentTime()}
        </div>
    `;

    box.appendChild(div);

    box.scrollTop = box.scrollHeight;
}

async function sendMessage(){

    const input = document.getElementById("userInput");

    const text = input.value.trim();

    if(!text) return;

    addMessage(text,"user");

    input.value = "";

    const res = await fetch("/web-chat",{

        method:"POST",

        headers:{
            "Content-Type":"application/json"
        },

        body:JSON.stringify({
            customer_phone:TEST_PHONE,
            message:text
        })
    });

    const data = await res.json();

    renderResponse(data);
}

function renderResponse(data){

    if(data.type === "text"){

        addMessage(data.message,"bot");
    }

    if(data.type === "product_options"){

        renderProductOptions(data.products);
    }

    if(data.type === "product_detail"){

        renderProductDetail(data);
    }
}

async function selectProduct(productName){

    // show selected message properly

    addMessage(
        `Selected ${productName}`,
        "user"
    );

    const res = await fetch("/web-select-product",{

        method:"POST",

        headers:{
            "Content-Type":"application/json"
        },

        body:JSON.stringify({

            customer_phone:TEST_PHONE,

            product_name:productName
        })
    });

    const data = await res.json();

    renderResponse(data);
}

async function raiseRequest(){

    const res = await fetch("/web-raise-request",{

        method:"POST",

        headers:{
            "Content-Type":"application/json"
        },

        body:JSON.stringify({
            customer_phone:TEST_PHONE
        })
    });

    const data = await res.json();

    renderResponse(data);
}

window.onload = ()=>{

    addMessage(
        "👋 Welcome to MediAssist AI\\n\\nSearch medicines and check availability instantly.",
        "bot"
    );
}

</script>

</body>
</html>

"""


# =========================================================
# APIs
# =========================================================

@app.route("/web-chat", methods=["POST"])
def web_chat():

    data = request.get_json(force=True)

    customer_phone = data.get(
        "customer_phone",
        "web_user"
    )

    user_text = data.get(
        "message",
        ""
    )

    response = get_bot_response(
        customer_phone,
        user_text
    )

    return jsonify(response)


@app.route("/web-select-product", methods=["POST"])
def web_select_product():

    data = request.get_json(force=True)

    customer_phone = data.get(
        "customer_phone",
        "web_user"
    )

    product_name = data.get(
        "product_name",
        ""
    ).strip().lower()

    df = load_inventory()

    matched = df[
        df["product_name"]
        .astype(str)
        .str.lower()
        == product_name
    ]

    if matched.empty:

        return jsonify({
            "type": "text",
            "message": (
                "⚠ Product not found.\n\n"
                "Please search again."
            )
        })

    product = matched.iloc[0].to_dict()

    session = get_customer_session(customer_phone)

    set_customer_session(customer_phone, {
        "flow": "selected_product",
        "product": product,
        "products": session.get("products", [])
    })

    return jsonify({
        "type": "product_detail",
        "message": format_product_details(product),
        "product": product,
        "available": product_is_available(product)
    })


@app.route("/web-raise-request", methods=["POST"])
def web_raise_request():

    data = request.get_json(force=True)

    customer_phone = data.get(
        "customer_phone",
        "web_user"
    )

    session = get_customer_session(customer_phone)

    product = session.get("product")

    if not product:

        return jsonify({
            "type": "text",
            "message": (
                "⚠ No product selected.\n\n"
                "Please select a medicine first."
            )
        })

    # move to quantity flow instead of direct save

    set_customer_session(customer_phone, {

        "flow": "awaiting_request_quantity",

        "product": product,

        "products": session.get("products", [])
    })

    return jsonify({
        "type": "text",
        "message": (
            f"📦 Enter quantity needed for "
            f"{product.get('product_name', '')}\n\n"
            "Example:\n"
            "2"
        )
    })

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

    # USE YOUR NEW PREMIUM BOT ENGINE
    response_data = get_bot_response(
        customer_phone,
        incoming_msg
    )

    # extract text message
    reply_text = response_data.get(
        "message",
        "Something went wrong."
    )

    # remove html line breaks if any
    reply_text = (
        str(reply_text)
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
    )

    twilio_response = MessagingResponse()

    twilio_response.message(reply_text)

    return Response(
        str(twilio_response),
        mimetype="application/xml"
    )

# =========================================================
# DEBUG
# =========================================================

@app.route("/debug-inventory")
def debug_inventory():

    df = load_inventory()

    return jsonify({
        "rows": len(df),
        "columns": df.columns.tolist(),
        "sample": df.head(5).to_dict(orient="records")
    })

# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    port = int(os.getenv("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )