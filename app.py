from flask import Flask, jsonify, request, send_from_directory
import json
import os

app = Flask(__name__)

DATA_FILE = "sectors.json"
SOURCE_GEOJSON = "sectors_grid_18334_wgs84.geojson"

# Перевірка наявності sectors.json — створюється при першому запуску
if not os.path.exists(DATA_FILE):
    print("🔄 Створення sectors.json із початкового GeoJSON...")
    with open(SOURCE_GEOJSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/sectors")
def sectors():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)

@app.route("/api/donate", methods=["POST"])
def donate():
    data = request.get_json()
    donor = data.get("donor", "").strip()
    desc = data.get("description", "").strip()
    sector_ids = set(data.get("sectors", []))

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        geo = json.load(f)

    for feature in geo["features"]:
        fid = feature["properties"].get("id")
        if fid in sector_ids:
            feature["properties"]["status"] = "liberated"
            feature["properties"]["label"] = donor
            feature["properties"]["description"] = desc
        # Перестрахування: зберегти grid
        if "grid" not in feature["properties"]:
            feature["properties"]["grid"] = [0, 0]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, indent=2)

    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=True)
