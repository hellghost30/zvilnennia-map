from flask import Flask, jsonify, request, send_from_directory
import json
import os

app = Flask(__name__)
DATA_FILE = "sectors.json"
# тепер беремо початковий GeoJSON із static/
SOURCE_GEOJSON = os.path.join(app.static_folder, "sectors_grid_18334_wgs84.geojson")

if not os.path.exists(DATA_FILE):
    print("🔄 Створення sectors.json із початкового GeoJSON...")
    with open(SOURCE_GEOJSON, "r", encoding="utf-8") as f:
        original = json.load(f)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(original, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/sectors")
def sectors():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

@app.route("/api/donate", methods=["POST"])
def donate():
    data = request.get_json()
    donor = data.get("donor", "").strip()
    desc = data.get("description", "").strip()
    sector_ids = set(data.get("sectors", []))

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        geo = json.load(f)

    for f in geo["features"]:
        fid = f.get("properties", {}).get("id")
        if fid in sector_ids:
            f["properties"]["status"] = "liberated"
            f["properties"]["label"] = donor
            f["properties"]["description"] = desc

        # гарантувати, що grid і geometry існують
        if "grid" not in f["properties"]:
            f["properties"]["grid"] = [0, 0]
        if not f.get("geometry") or not f["geometry"].get("coordinates"):
            print(f"⚠️ Увага: сектор {fid} має некоректну геометрію")

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(geo, f, ensure_ascii=False, indent=2)

    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=True)
