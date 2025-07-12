
from flask import Flask, jsonify, request, send_from_directory
import json

app = Flask(__name__)
DATA_FILE = "sectors.json"

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
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        sectors = json.load(f)
    for f in sectors["features"]:
        if f["properties"]["id"] in data["sectors"]:
            f["properties"]["status"] = "liberated"
            f["properties"]["label"] = data["donor"]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(sectors, f, ensure_ascii=False)
    return jsonify(success=True)
