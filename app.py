from flask import Flask, jsonify, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy
import os, json

# Абсолютний шлях до каталогу проекту
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Тепер GeoJSON лежить у static/
GEOJSON_FILE = os.path.join(BASE_DIR, 'static', 'sectors_grid_18334_wgs84.geojson')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///sectors.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Sector(db.Model):
    __tablename__ = 'sectors'
    id          = db.Column(db.String, primary_key=True)
    geometry    = db.Column(db.JSON, nullable=False)
    grid        = db.Column(db.JSON, nullable=False)
    status      = db.Column(db.String, default='free')
    label       = db.Column(db.String, default='')
    description = db.Column(db.String, default='')

@app.before_first_request
def init_db():
    db.create_all()
    # Якщо таблиця порожня — насіваємо з GeoJSON
    if Sector.query.first() is None:
        with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
            gj = json.load(f)
        for feat in gj['features']:
            p = feat['properties']
            db.session.add(Sector(
                id=p['id'],
                geometry=feat['geometry'],
                grid=p.get('grid', [0,0]),
                status=p.get('status','free'),
                label=p.get('label',''),
                description=p.get('description','')
            ))
        db.session.commit()

@app.route('/api/sectors')
def sectors():
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
    donor, desc, ids = data.get('donor',''), data.get('description',''), data.get('sectors',[])
    Sector.query.filter(Sector.id.in_(ids)).update({
        'status': 'liberated',
        'label': donor,
        'description': desc
    }, synchronize_session=False)
    db.session.commit()
    return jsonify(success=True)

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    app.run(debug=True)
