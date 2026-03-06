from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)


@app.route("/api/status")
def status():
    return jsonify({
        "message": "Runway Shield is online. All systems operational.",
        "status": "ok",
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
