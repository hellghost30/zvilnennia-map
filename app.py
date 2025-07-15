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
MONOBANK_JAR_ID = "8ZofGM9kef"
MONOBANK_TOKEN = os.environ.get("MONOBANK_TOKEN")
MONOBANK_API = f"https://api.monobank.ua/personal/statement/{MONOBANK_JAR_ID}/"
REDIRECT_URL_BASE = "https://zvilnennia-map.onrender.com/success"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sectors.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# === Моделі ===
class Sector(db.Model):
    id = db.Column(db.String, primary_key=True)
    geometry = db.Column(db.JSON, nullable=False)
    grid = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String, default='free')
    label = db.Column(db.String, default='')
    description = db.Column(db.String, default='')
    reserved_until = db.Column(db.DateTime, nullable=True)
    reserved_by = db.Column(db.String, nullable=True)

class Payment(db.Model):
    id = db.Column(db.String, primary_key=True)
    client_id = db.Column(db.String, nullable=False)
    donor = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    sectors = db.Column(db.JSON, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fulfilled = db.Column(db.Boolean, default=False)

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
                grid=p.get('grid', [0, 0]),
                status=p.get('status', 'free'),
                label=p.get('label', ''),
                description=p.get('description', '')
            ))
        db.session.commit()

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
    return jsonify({'type': 'FeatureCollection', 'features': features})

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

    payment = Payment(
        id=payment_id,
        client_id=client_id,
        donor=donor,
        description=desc,
        sectors=sectors,
        amount=amount
    )
    db.session.add(payment)
    db.session.commit()

    url = f"https://send.monobank.ua/jar/{MONOBANK_JAR_ID}?amount={amount}00&comment={payment_id}"
    return jsonify({'payment_url': url})

@app.route('/api/check-donations')
def check_donations():
    since = int((datetime.utcnow() - timedelta(days=3)).timestamp())
    headers = {"X-Token": MONOBANK_TOKEN}
    r = requests.get(MONOBANK_API + str(since), headers=headers)
    if r.status_code != 200:
        return jsonify({'error': 'Не вдалося отримати історію транзакцій'}), 500

    payments = Payment.query.filter_by(fulfilled=False).all()
    mapping = {p.id: p for p in payments}
    txns = r.json()

    updated = 0
    for txn in txns:
        comment = txn.get("comment", "").strip()
        amount_uah = txn.get("amount", 0) // 100
        if comment in mapping:
            p = mapping[comment]
            if amount_uah >= p.amount:
                sectors = Sector.query.filter(Sector.id.in_(p.sectors)).all()
                for s in sectors:
                    s.status = 'liberated'
                    s.label = p.donor
                    s.description = p.description
                    s.reserved_by = None
                    s.reserved_until = None
                p.fulfilled = True
                updated += 1

    db.session.commit()
    return jsonify({'updated': updated})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/success')
def success():
    return """
    <h2>✅ Оплата пройшла успішно!</h2>
    <p>Сектори будуть звільнені після підтвердження оплати. Ви можете повернутися на <a href="/">головну сторінку</a>.</p>
    """

if __name__ == '__main__':
    app.run(debug=True)
