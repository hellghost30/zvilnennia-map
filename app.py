import os
import json
import uuid
import requests
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy

# === Конфігурація ===
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
GEOJSON_FILE = os.path.join(BASE_DIR, 'sectors_grid_18334_wgs84.geojson')
MONOBANK_TOKEN = os.environ.get("MONOBANK_TOKEN")
MONOBANK_JAR_ID = "8ZofGM9kef"
MONOBANK_API = "https://api.monobank.ua/api/merchant/invoice/create"
WEBHOOK_URL = "https://zvilnennia-map.onrender.com/api/monobank-webhook"
REDIRECT_URL_BASE = "https://zvilnennia-map.onrender.com/success"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sectors.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# === Моделі ===
class Sector(db.Model):
    __tablename__ = 'sectors'
    id = db.Column(db.String, primary_key=True)
    geometry = db.Column(db.JSON, nullable=False)
    grid = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String, default='free')
    label = db.Column(db.String, default='')
    description = db.Column(db.String, default='')
    reserved_until = db.Column(db.DateTime, nullable=True)
    reserved_by = db.Column(db.String, nullable=True)

class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.String, primary_key=True)
    client_id = db.Column(db.String, nullable=False)
    donor = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    sectors = db.Column(db.JSON, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fulfilled = db.Column(db.Boolean, default=False)

# === Ініціалізація БД ===
@app.before_first_request
def init_db():
    db.create_all()
    if Sector.query.first() is None:
        with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
            gj = json.load(f)
        for feat in gj['features']:
            p = feat['properties']
            db.session.add(Sector(
                id=p['id'],
                geometry=feat['geometry'],
                grid=p.get('grid', [0,0]),
                status=p.get('status', 'free'),
                label=p.get('label', ''),
                description=p.get('description', '')
            ))
        db.session.commit()

# === API ===
@app.route('/api/sectors')
def sectors():
    now = datetime.utcnow()
    expired = Sector.query.filter(Sector.status == 'reserved', Sector.reserved_until < now).all()
    for s in expired:
        s.status = 'free'
        s.reserved_until = None
        s.reserved_by = None
    if expired:
        db.session.commit()

    features = []
    for s in Sector.query.all():
        features.append({
            'type': 'Feature',
            'geometry': s.geometry,
            'properties': {
                'id': s.id,
                'grid': s.grid,
                'status': s.status,
                'label': s.label,
                'description': s.description
            }
        })
    return jsonify({ 'type': 'FeatureCollection', 'features': features })

@app.route('/api/reserve', methods=['POST'])
def reserve():
    data = request.get_json()
    ids = data.get('sectors', [])
    client_id = data.get('client_id')
    if not client_id:
        return jsonify({'error': 'Missing client ID'}), 400

    now = datetime.utcnow()
    expire_time = now + timedelta(minutes=10)

    sectors = Sector.query.filter(Sector.id.in_(ids)).all()
    for s in sectors:
        if s.status == 'liberated':
            return jsonify({'error': 'Сектор зайнято'}), 400
        if s.status == 'reserved' and s.reserved_by != client_id:
            return jsonify({'error': 'Сектор уже в броні іншого користувача'}), 400

    for s in sectors:
        s.status = 'reserved'
        s.reserved_until = expire_time
        s.reserved_by = client_id

    db.session.commit()
    return jsonify(success=True)

@app.route('/api/create-payment', methods=['POST'])
def create_payment():
    data = request.get_json()
    donor = data.get('donor', '')
    desc = data.get('description', '')
    sectors = data.get('sectors', [])
    client_id = data.get('client_id')
    if not donor or not sectors or not client_id:
        return jsonify({'error': 'Недостатньо даних'}), 400

    amount = len(sectors) * 35
    payment_id = str(uuid.uuid4())

    p = Payment(
        id=payment_id,
        client_id=client_id,
        donor=donor,
        description=desc,
        sectors=sectors,
        amount=amount
    )
    db.session.add(p)
    db.session.commit()

    invoice_payload = {
        "amount": int(amount * 100),
        "ccy": 980,
        "redirectUrl": f"{REDIRECT_URL_BASE}?id={payment_id}",
        "webHookUrl": WEBHOOK_URL,
        "merchantPaymInfo": {
            "reference": payment_id,
            "destination": f"Звільнення секторів: {donor}"
        }
    }

    headers = {"X-Token": MONOBANK_TOKEN}
    r = requests.post(MONOBANK_API, json=invoice_payload, headers=headers)
    if r.status_code == 200:
        url = r.json().get("pageUrl")
        return jsonify({"payment_url": url})
    else:
        return jsonify({"error": "Не вдалося створити рахунок"}), 500

@app.route('/api/monobank-webhook', methods=['POST'])
def monobank_webhook():
    data = request.get_json()
    if data.get('type') != 'IncomingPayment':
        return jsonify({'ignored': True})

    info = data.get('data', {})
    amount_uah = info.get('amount', 0) // 100
    comment = info.get('comment', '').strip()

    payment = Payment.query.filter_by(id=comment, fulfilled=False).first()
    if not payment:
        return jsonify({'error': 'Payment not found'}), 404

    if amount_uah < payment.amount:
        return jsonify({'error': 'Недостатня сума'}), 400

    sectors = Sector.query.filter(Sector.id.in_(payment.sectors)).all()
    for s in sectors:
        s.status = 'liberated'
        s.label = payment.donor
        s.description = payment.description
        s.reserved_until = None
        s.reserved_by = None

    payment.fulfilled = True
    db.session.commit()
    print(f"✅ Оплата {amount_uah} грн — звільнено {len(sectors)} секторів")
    return jsonify({'success': True})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    app.run(debug=True)
