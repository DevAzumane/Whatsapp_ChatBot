# Local Store WhatsApp Product Availability Assistant - MVP

This is a ready-to-run MVP for your local store product availability assistant idea.

## Features

- Product search across multiple shop types
- Fuzzy matching for product names, brands, variants, and categories
- Product availability response
- Customer request capture when product is unavailable
- Admin dashboard
- CSV inventory upload
- API endpoint for future WhatsApp integration

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

Admin dashboard:

```text
http://127.0.0.1:5000/admin
```

## Test API

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"Dolo 650\",\"customer_phone\":\"9999999999\",\"shop_type\":\"Medical Shop\"}"
```

## Inventory CSV Format

```text
shop_id, shop_name, shop_type, product_name, category, brand, variant, price, quantity, status
```

## WhatsApp Integration Later

Connect `/api/chat` to:

- WhatsApp Cloud API
- Twilio WhatsApp API
- Interakt
- WATI
- AiSensy

Current project is built as a local web MVP first.
