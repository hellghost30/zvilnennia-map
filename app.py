from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os, json

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
GEOJSON_FILE = os.path.join(BASE_DIR, 'sectors_grid_18334_wgs84.geojson')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sectors.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Sector(db.Model):
    __tablename__ = 'sectors'
    id              = db.Column(db.String, primary_key=True)
    geometry        = db.Column(db.JSON, nullable=False)
    grid            = db.Column(db.JSON, nullable=False)
    status          = db.Column(db.String, default='free')  # free, reserved, liberated
    label           = db.Column(db.String, default='')
    description     = db.Column(db.String, default='')
    reserved_until  = db.Column(db.DateTime, nullable=True)
    reserved_by     = db.Column(db.String, nullable=True)  # 🔑 додаємо поле

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

@app.route('/api/sectors')
def sectors():
    now = datetime.utcnow()

    # Звільняємо прострочені броні
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

@app.route('/api/donate', methods=['POST'])
def donate():
    data = request.get_json()
    donor = data.get('donor', '')
    desc = data.get('description', '')
    ids = data.get('sectors', [])

    # 🔄 оновлюємо поля
    Sector.query.filter(Sector.id.in_(ids)).update({
        'status': 'liberated',
        'label': donor,
        'description': desc,
        'reserved_until': None,
        'reserved_by': None
    }, synchronize_session=False)

    db.session.commit()
    return jsonify(success=True)

@app.route('/api/reserve', methods=['POST'])
def reserve():
    data = request.get_json()
    ids = data.get('sectors', [])
    client_id = data.get('client_id')
    if not client_id:
        return jsonify({'error': 'Missing client ID'}), 400

    now = datetime.utcnow()
    expire_time = now + timedelta(minutes=5)

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

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    app.run(debug=True)
@app.route('/api/monobank-webhook', methods=['POST'])
def monobank_webhook():
    data = request.get_json()

    if data.get('type') == 'IncomingPayment':
        info = data.get('data', {})
        amount_uah = info.get('amount', 0) / 100  # копійки → гривні
        comment = info.get('comment', '').strip()
        from_card = info.get('sourceCardMask', '****')

        print(f"💳 Донат {amount_uah} грн від {from_card} | Коментар: {comment}")
        
        # TODO: Тут можна обробити автоматичне звільнення заброньованих секторів
        # по коментарю, сумі, або іншим ознакам

    return jsonify(success=True)
