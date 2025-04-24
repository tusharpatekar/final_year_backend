from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from google.oauth2 import id_token
from google.auth.transport import requests
import sqlite3
import os
import base64
import logging
import requests
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Set CORS based on environment
frontend_origin = os.getenv('FRONTEND_ORIGIN', 'https://happy-stone-0f87c1c1e.6.azurestaticapps.net')
CORS(app, resources={
    r"/*": {
        "origins": [frontend_origin],
        "methods": ["GET", "POST", "OPTIONS"],  # Explicitly allow methods
        "allow_headers": ["Content-Type", "Authorization"],  # Allow headers used by Axios
        "supports_credentials": True  # Optional, if cookies or credentials are used
    }
})
app.secret_key = os.urandom(24)
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)
# Database setup
def setup_database():
    conn = sqlite3.connect('store.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def connect_db():
    return sqlite3.connect('store.db')

# Configuration
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'bucket')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Routes
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/google-login', methods=['POST'])
def google_login():
    data = request.get_json()
    token = data.get('token')
    try:
        CLIENT_ID = "763127770724-isjj3oae0bug2vk42ueo8090h4je9jpa.apps.googleusercontent.com"
        idinfo = id_token.verify_oauth2_token(token, requests.Request(), CLIENT_ID)
        email = idinfo.get('email')

        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()

        if not user:
            cursor.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, ''))
            conn.commit()

        conn.close()
        return jsonify({"message": "Google Login successful", "email": email, "status": "true"}), 200
    except ValueError:
        return jsonify({"error": "Invalid token", "status": "false"}), 400

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, password))
        conn.commit()
        conn.close()
        return jsonify({"message": "Signup successful"}), 200
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already exists"}), 400

@app.route('/login', methods=['POST'])
def login():
    app.logger.info("Received request at /login endpoint")  # Log request arrival
    data = request.get_json()
    app.logger.debug(f"Request data: {data}")  # Log the incoming data
    email = data.get('email')
    password = data.get('password')
    app.logger.debug(f"Extracted email: {email}, password: {password}")  # Log extracted values

    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ? AND password = ?', (email, password))
    user = cursor.fetchone()
    conn.close()

    if user:
        app.logger.info(f"User {email} logged in successfully.")
        return jsonify({"message": "Login successful"}), 200
    app.logger.warning(f"Failed login attempt for email: {email}")
    return jsonify({"error": "Invalid email or password"}), 401

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/plantdisease', methods=['POST'])
def plantdisease():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Invalid file type"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    res = get_more_info(filepath)
    return jsonify({"result": res})

# Helper function for plant disease info using Google Gemini API
def get_more_info(filepath):
    with open(filepath, 'rb') as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')

    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent"
    api_key = "AIzaSyDLryzPzgltN6XffTSv-_85mZUig6bwgbg"
    url = f"{endpoint}?key={api_key}"

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": encoded_image}},
                {"text": "Analyze this image and detect plant disease. Provide the response with crop name, disease, and suggestions for treatment or management. If the image is not clear or you are uncertain, return only 'unable to fetch'."}
            ]
        }]
    }

    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        result = response.json()
        return result['candidates'][0]['content']['parts'][0]['text']
    return f"Error: {response.status_code}, {response.text}"

if __name__ == "__main__":
    setup_database()
    app.run(host='0.0.0.0', port=5000)