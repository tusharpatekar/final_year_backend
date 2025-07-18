from flask import Flask, render_template, request, jsonify
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

import sqlite3
import os
import base64
from flask_cors import CORS
import logging
import requests
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
# API_URL = "http://localhost:5173"
API_URL = "https://nice-glacier-080ccc81e.1.azurestaticapps.net"
# API_URL = os.getenv('API_URL', 'https://salmon-pebble-0a7fc0b1e.6.azurestaticapps.net')

CORS(app, supports_credentials=True, origins=[API_URL], allow_headers=["Content-Type"], methods=["POST", "GET", "OPTIONS"])
app.secret_key = os.urandom(24)
logging.basicConfig(level=logging.DEBUG)
app.logger.setLevel(logging.DEBUG)

# Database setup
def setup_database():
    with sqlite3.connect('store.db', timeout=10) as conn:
        conn.execute('PRAGMA journal_mode=WAL;')  # Enable WAL mode
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        conn.commit()

def connect_db():
    # Set timeout to 10 seconds to wait for locks
    return sqlite3.connect('store.db', timeout=10)

# File-upload config
BASE_DIR = os.path.dirname(os.path.realpath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'bucket')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# === ROUTES ===

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/google-login', methods=['POST'])
def google_login():
    data = request.get_json()
    token = data.get('token') or data.get('credential')  # Handle both 'token' and 'credential' keys
    # print(token)
    try:
        app.logger.info(f"Received token: {token}")
        CLIENT_ID = '763127770724-isjj3oae0bug2vk42ueo8090h4je9jpa.apps.googleusercontent.com'
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            CLIENT_ID
        )
        app.logger.info(f"google info : {idinfo}")
        email = idinfo.get('email')

        with connect_db() as conn:
            conn.execute('PRAGMA journal_mode=WAL;')  # Ensure WAL mode
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM users WHERE email = ?',
                (email,)
            )
            user = cursor.fetchone()
            if not user:
                cursor.execute(
                    'INSERT INTO users (email, password) VALUES (?, ?)',
                    (email, '')
                )
                conn.commit()

        return jsonify({
            "message": "Google Login successful",
            "email": email,
            "status": "true"
        }), 200

    except ValueError as ve:
        app.logger.error(f"Google login failed: {ve}")
        return jsonify({
            "error": "Invalid token",
            "status": "false"
        }), 400
    except Exception as e:
        app.logger.error(f"Unexpected error in google-login: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    try:
        with connect_db() as conn:
            conn.execute('PRAGMA journal_mode=WAL;')  # Ensure WAL mode
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO users (email, password) VALUES (?, ?)',
                (email, password)
            )
            conn.commit()
        app.logger.info(f"User {email} signed up successfully")
        return jsonify({"message": "Signup successful"}), 200

    except sqlite3.IntegrityError:
        app.logger.warning(f"Signup failed: Email {email} already exists")
        return jsonify({"error": "Email already exists"}), 400
    except sqlite3.OperationalError as oe:
        app.logger.error(f"Database error in signup: {oe}")
        return jsonify({"error": "Database is temporarily unavailable"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in signup: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/login', methods=['POST'])
def login():
    app.logger.info("Received request at /login endpoint")
    data = request.get_json(silent=True)
    app.logger.debug(f"Request data: {data}")

    email = data.get('email') if data else None
    password = data.get('password') if data else None
    app.logger.debug(f"Extracted email: {email}, password: {password}")

    try:
        with connect_db() as conn:
            conn.execute('PRAGMA journal_mode=WAL;')  # Ensure WAL mode
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM users WHERE email = ? AND password = ?',
                (email, password)
            )
            user = cursor.fetchone()

        if user:
            app.logger.info(f"User {email} logged in successfully")
            return jsonify({"message": "Login successful"}), 200

        app.logger.warning(f"Failed login attempt for email: {email}")
        return jsonify({"error": "Invalid email or password"}), 401

    except sqlite3.OperationalError as oe:
        app.logger.error(f"Database error in login: {oe}")
        return jsonify({"error": "Database is temporarily unavailable"}), 503
    except Exception as e:
        app.logger.error(f"Unexpected error in login: {e}")
        return jsonify({"error": "Server error"}), 500

def allowed_file(filename):
    return (
        '.' in filename
        and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    )

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
    # Read and encode the image
    with open(filepath, 'rb') as image_file:
        encoded_image = base64.b64encode(image_file.read()).decode('utf-8')
 
    # Gemini 1.5 Pro API endpoint and key
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    api_key = "AIzaSyA5KSS8BH-zwH7-nEkem7mkfCStnbIA_z0"  # Store your API key in an environment variable
 
 
    url = f"{endpoint}?key={api_key}"
 
    headers = {
        "Content-Type": "application/json"
    }
 
    # Payload for Gemini 1.5 Pro
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": encoded_image
                        }
                    },
                    {
                        "text": "Analyze this image and detect plant disease. Provide the response with crop name, disease, and suggestions for treatment or management. If the image is not clear or you are uncertain, return only 'unable to fetch'."
                    }
                ]
            }
        ]
    }
 
    # Send request to Gemini API
    response = requests.post(url, headers=headers, json=payload)
 
    if response.status_code == 200:
        result = response.json()
        # Extract the generated text from Gemini's response
        return result['candidates'][0]['content']['parts'][0]['text']
    else:
        return f"Error: {response.status_code}, {response.text}"
 
if __name__ == "__main__":
    setup_database()
    app.run(host='0.0.0.0', port=5000, debug=True)