from flask import Flask, request, jsonify, send_file, send_from_directory, make_response, abort
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from datetime import datetime, timedelta
import json
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename
import uuid
from decimal import Decimal
import mimetypes
import logging
import traceback
from functools import wraps
from urllib.parse import urlparse
import requests
from io import BytesIO

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['STATIC_FOLDER'] = 'static'

# Create static folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

# Create a simple placeholder image if it doesn't exist
placeholder_path = os.path.join('static', 'placeholder.png')
if not os.path.exists(placeholder_path):
    try:
        # Try to create a simple placeholder with PIL if available
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (300, 300), color=(102, 126, 234))
            draw = ImageDraw.Draw(img)
            draw.text((150, 150), "No Image", fill="white", anchor="mm")
            img.save(placeholder_path)
            logger.info("✓ Created placeholder image")
        except:
            # If PIL not available, create a simple text file and rename
            with open(placeholder_path, 'wb') as f:
                f.write(b'')
            logger.warning("Created empty placeholder file")
    except Exception as e:
        logger.warning(f"Could not create placeholder image: {e}")

# ==================== CONSTANT LOGIN CREDENTIALS ====================
CONSTANT_EMAIL = "KARANJASHOESTORE@GMAIL.COM"
CONSTANT_PASSWORD = "0726539216"
CONSTANT_USER_ID = "1"
CONSTANT_USER_NAME = "Karanja Shoe Store"
CONSTANT_USER_ROLE = "admin"

# ==================== BACKBLAZE B2 CONFIGURATION ====================
B2_CONFIG = {
    'BUCKET_NAME': os.environ.get('B2_BUCKET_NAME', 'KARANJASH'),
    'BUCKET_ID': os.environ.get('B2_BUCKET_ID', '325093e8d52f70a795cd0d15'),
    'ENDPOINT': os.environ.get('B2_ENDPOINT', 's3.eu-central-003.backblazeb2.com'),
    'REGION': os.environ.get('B2_REGION', 'eu-central-003'),
    'CDN_URL': os.environ.get('B2_CDN_URL', 'https://f005.backblazeb2.com/file/KARANJASH'),
    'CREATED_DATE': 'February 20, 2026',
    
    # APPLICATION KEY (KARANJASH)
    'ACCESS_KEY_ID': os.environ.get('B2_ACCESS_KEY_ID', '00320385f075dd50000000002'),
    'SECRET_ACCESS_KEY': os.environ.get('B2_SECRET_ACCESS_KEY', 'K0034O1CRh5jaFZRSwDBEf5e40lGJhY'),
    
    'TYPE': 'Private',
    'ENCRYPTION': 'Disabled',
    
    'DATA_PATHS': {
        'PRODUCTS': 'data/products.json',
        'SALES': 'data/sales.json',
        'NOTIFICATIONS': 'data/notifications.json',
        'SETTINGS': 'data/settings.json',
        'MONTHLY_CATEGORY_SALES': 'data/monthly_category_sales.json',
        'DAILY_STATEMENTS': 'data/daily_statements.json',
        'BUDGET_PLANS': 'data/budget_plans.json',
        'SALE_STATEMENTS': 'data/sale_statements.json',
        'B2_IMAGES': 'data/b2_images.json'
    }
}

# Initialize Backblaze B2 client
try:
    b2_client = boto3.client(
        's3',
        endpoint_url=f'https://{B2_CONFIG["ENDPOINT"]}',
        aws_access_key_id=B2_CONFIG['ACCESS_KEY_ID'],
        aws_secret_access_key=B2_CONFIG['SECRET_ACCESS_KEY'],
        config=Config(
            signature_version='s3v4',
            region_name=B2_CONFIG['REGION'],
            retries={'max_attempts': 3}
        )
    )
    logger.info("✓ Backblaze B2 client initialized successfully")
    
    # Test the connection by listing buckets
    buckets = b2_client.list_buckets()
    logger.info(f"✓ Successfully connected to B2. Available buckets: {[b['Name'] for b in buckets['Buckets']]}")
    
    # Test if we can access the specific bucket
    try:
        b2_client.head_bucket(Bucket=B2_CONFIG['BUCKET_NAME'])
        logger.info(f"✓ Successfully accessed bucket: {B2_CONFIG['BUCKET_NAME']}")
        B2_AVAILABLE = True
    except ClientError as e:
        logger.error(f"✗ Cannot access bucket {B2_CONFIG['BUCKET_NAME']}: {e}")
        B2_AVAILABLE = False
        
except Exception as e:
    logger.error(f"✗ Failed to initialize B2 client: {e}")
    B2_AVAILABLE = False
    b2_client = None

# ==================== ENSURE FOLDERS EXIST IN B2 ====================
def ensure_b2_folders():
    """Ensure required folders exist in B2 bucket"""
    if not b2_client or not B2_AVAILABLE:
        logger.warning("B2 not available, cannot create folders")
        return False
    
    folders = ['data', 'products']
    created_folders = []
    existing_folders = []
    
    logger.info("=" * 50)
    logger.info("CHECKING B2 FOLDERS")
    logger.info("=" * 50)
    
    for folder in folders:
        try:
            # Check if folder exists by looking for .keep file
            test_key = f"{folder}/.keep"
            try:
                b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key=test_key)
                logger.info(f"✓ Folder already exists: {folder}/")
                existing_folders.append(folder)
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    # Folder doesn't exist, create it
                    logger.info(f"Creating folder: {folder}/")
                    b2_client.put_object(
                        Bucket=B2_CONFIG['BUCKET_NAME'],
                        Key=test_key,
                        Body=b'',
                        ContentType='text/plain'
                    )
                    logger.info(f"✓ Successfully created folder: {folder}/")
                    created_folders.append(folder)
                else:
                    logger.error(f"Error checking folder {folder}: {e}")
        except Exception as e:
            logger.error(f"Error ensuring folder {folder}: {e}")
    
    logger.info("=" * 50)
    if created_folders:
        logger.info(f"✅ Created folders: {', '.join(created_folders)}")
    if existing_folders:
        logger.info(f"✅ Existing folders: {', '.join(existing_folders)}")
    logger.info("=" * 50)
    
    return True

# ==================== INITIALIZE B2 FOLDERS ====================
# Call this function to create folders when app starts
if B2_AVAILABLE and b2_client:
    ensure_b2_folders()
else:
    logger.warning("⚠ B2 not available - folders will not be created")

# ==================== EXTENSIONS ====================
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "max_age": 3600
    },
    r"/static/*": {
        "origins": ["*"]
    },
    r"/images/*": {
        "origins": ["*"]
    }
})
jwt = JWTManager(app)

# ==================== CUSTOM JSON ENCODER ====================
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)

app.json_encoder = CustomJSONEncoder

# ==================== OPTIONAL JWT DECORATOR ====================
def optional_jwt_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            try:
                verify_jwt_in_request(optional=True)
            except Exception as e:
                logger.debug(f"JWT verification failed (optional): {e}")
            return fn(*args, **kwargs)
        return decorator
    return wrapper

# ==================== B2 DATA STORAGE MANAGER ====================
class B2DataStore:
    def __init__(self, b2_client, bucket_name):
        self.b2_client = b2_client
        self.bucket_name = bucket_name
        self.cache = {}
        self.initialized = False
        self.load_all_data()
    
    def _ensure_data_directory(self):
        if not self.b2_client:
            return False
        try:
            test_key = 'data/.keep'
            try:
                self.b2_client.head_object(Bucket=self.bucket_name, Key=test_key)
            except ClientError:
                self.b2_client.put_object(
                    Bucket=self.bucket_name,
                    Key=test_key,
                    Body=b'',
                    ContentType='text/plain'
                )
            return True
        except Exception as e:
            logger.error(f"Error ensuring data directory: {e}")
            return False
    
    def _read_json_from_b2(self, b2_key):
        if not self.b2_client:
            return {}
        try:
            response = self.b2_client.get_object(
                Bucket=self.bucket_name,
                Key=b2_key
            )
            content = response['Body'].read().decode('utf-8')
            return json.loads(content) if content.strip() else {}
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"Creating new data file: {b2_key}")
                return {}
            logger.error(f"Error reading {b2_key}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error reading {b2_key}: {e}")
            return {}
    
    def _write_json_to_b2(self, b2_key, data):
        if not self.b2_client:
            return False
        try:
            json_str = json.dumps(data, cls=CustomJSONEncoder, indent=2)
            self.b2_client.put_object(
                Bucket=self.bucket_name,
                Key=b2_key,
                Body=json_str.encode('utf-8'),
                ContentType='application/json',
                CacheControl='no-cache'
            )
            logger.info(f"✓ Successfully wrote {b2_key} to B2")
            return True
        except Exception as e:
            logger.error(f"✗ Error writing {b2_key}: {e}")
            return False
    
    def load_all_data(self):
        if not self.b2_client:
            return
        
        self._ensure_data_directory()
        
        self.cache['products'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['PRODUCTS'])
        self.cache['sales'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SALES'])
        self.cache['notifications'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['NOTIFICATIONS'])
        self.cache['settings'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SETTINGS'])
        self.cache['monthly_category_sales'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['MONTHLY_CATEGORY_SALES'])
        self.cache['daily_statements'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['DAILY_STATEMENTS'])
        self.cache['budget_plans'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['BUDGET_PLANS'])
        self.cache['sale_statements'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SALE_STATEMENTS'])
        self.cache['b2_images'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'])
        
        # Initialize defaults
        if not isinstance(self.cache.get('products'), list):
            self.cache['products'] = []
        if not isinstance(self.cache.get('sales'), list):
            self.cache['sales'] = []
        if not isinstance(self.cache.get('notifications'), list):
            self.cache['notifications'] = []
        if not isinstance(self.cache.get('settings'), dict):
            self.cache['settings'] = {
                'currency': 'KES',
                'low_stock_threshold': 3,
                'old_stock_days': 30,
                'theme': 'light',
                'b2_bucket': B2_CONFIG['BUCKET_ID'],
                'storage': 'b2'
            }
        if not isinstance(self.cache.get('monthly_category_sales'), dict):
            self.cache['monthly_category_sales'] = {}
        if not isinstance(self.cache.get('daily_statements'), list):
            self.cache['daily_statements'] = []
        if not isinstance(self.cache.get('budget_plans'), list):
            self.cache['budget_plans'] = []
        if not isinstance(self.cache.get('sale_statements'), list):
            self.cache['sale_statements'] = []
        if not isinstance(self.cache.get('b2_images'), list):
            self.cache['b2_images'] = []
        
        self.initialized = True
        logger.info("✓ All data loaded from Backblaze B2")
        logger.info(f"  Products: {len(self.cache['products'])}")
        logger.info(f"  Sales: {len(self.cache['sales'])}")
        logger.info(f"  Images: {len(self.cache['b2_images'])}")
    
    @property
    def products(self):
        return self.cache.get('products', [])
    
    def save_products(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['PRODUCTS'], self.products)
    
    @property
    def sales(self):
        return self.cache.get('sales', [])
    
    def save_sales(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SALES'], self.sales)
    
    @property
    def notifications(self):
        return self.cache.get('notifications', [])
    
    def save_notifications(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['NOTIFICATIONS'], self.notifications)
    
    @property
    def settings(self):
        return self.cache.get('settings', {})
    
    def save_settings(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SETTINGS'], self.settings)
    
    @property
    def monthly_category_sales(self):
        return self.cache.get('monthly_category_sales', {})
    
    def save_monthly_category_sales(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['MONTHLY_CATEGORY_SALES'], self.monthly_category_sales)
    
    @property
    def daily_statements(self):
        return self.cache.get('daily_statements', [])
    
    def save_daily_statements(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['DAILY_STATEMENTS'], self.daily_statements)
    
    @property
    def budget_plans(self):
        return self.cache.get('budget_plans', [])
    
    def save_budget_plans(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['BUDGET_PLANS'], self.budget_plans)
    
    @property
    def sale_statements(self):
        return self.cache.get('sale_statements', [])
    
    def save_sale_statements(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SALE_STATEMENTS'], self.sale_statements)
    
    @property
    def b2_images(self):
        return self.cache.get('b2_images', [])
    
    def save_b2_images(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'], self.b2_images)

# Initialize Data Store
if not B2_AVAILABLE or not b2_client:
    logger.error("✗ Backblaze B2 is required for data storage. Please check your credentials.")
    logger.warning("Continuing without B2 - only static files will work")
    data_store = None
else:
    data_store = B2DataStore(b2_client, B2_CONFIG['BUCKET_NAME'])
    logger.info("✓ Using Backblaze B2 for ALL data storage")

# ==================== SIGNED URL GENERATION ====================

def generate_signed_url(s3_key, expiration=604800):
    """
    Generate a pre-signed URL for private B2 bucket access
    expiration: time in seconds (default 7 days)
    """
    if not b2_client or not s3_key:
        return None
    try:
        # Clean the s3_key - remove any leading slashes
        if s3_key.startswith('/'):
            s3_key = s3_key[1:]
        
        # Generate the signed URL
        url = b2_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': B2_CONFIG['BUCKET_NAME'],
                'Key': s3_key
            },
            ExpiresIn=expiration,
            HttpMethod='GET'
        )
        
        logger.info(f"✓ Generated signed URL for: {s3_key}")
        return url
    except Exception as e:
        logger.error(f"Error generating signed URL for {s3_key}: {e}")
        return None

def extract_s3_key_from_url(url):
    """Extract S3 key from B2 URL"""
    if not url:
        return None
    try:
        # Handle different URL formats
        if 'backblazeb2.com' in url:
            parsed = urlparse(url)
            path = parsed.path
            
            if path.startswith('/file/' + B2_CONFIG['BUCKET_NAME'] + '/'):
                key = path.replace('/file/' + B2_CONFIG['BUCKET_NAME'] + '/', '')
            elif path.startswith('/' + B2_CONFIG['BUCKET_NAME'] + '/'):
                key = path.replace('/' + B2_CONFIG['BUCKET_NAME'] + '/', '')
            else:
                key = path.lstrip('/')
            
            if '?' in key:
                key = key.split('?')[0]
            
            return key
        elif '/api/images/' in url:
            return url.replace('/api/images/', '')
        
        return url
    except Exception as e:
        logger.error(f"Error extracting S3 key: {e}")
        return None

def verify_image_exists(s3_key):
    """Verify that an image exists in B2"""
    if not b2_client or not s3_key:
        return False
    try:
        # Clean the s3_key
        if s3_key.startswith('/'):
            s3_key = s3_key[1:]
        
        b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key=s3_key)
        logger.info(f"✓ Image exists in B2: {s3_key}")
        return True
    except ClientError as e:
        logger.error(f"Image not found in B2: {s3_key} - {e}")
        return False

# ==================== IMAGE PROXY ROUTE ====================

@app.route('/api/images/<path:s3_key>')
@optional_jwt_required()
def proxy_image(s3_key):
    """Proxy images from private B2 bucket with authentication"""
    if not b2_client:
        logger.warning("B2 client not available, serving placeholder")
        return send_file('static/placeholder.png')
    
    logger.info(f"Attempting to serve image: {s3_key}")
    
    # Clean the key - don't add products/ prefix if it's already there
    clean_key = s3_key
    logger.info(f"Looking for key: {clean_key} in bucket: {B2_CONFIG['BUCKET_NAME']}")
    
    try:
        # Try to get the object from B2
        response = b2_client.get_object(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            Key=clean_key
        )
        
        # Get the image data and content type
        image_data = response['Body'].read()
        content_type = response.get('ContentType', 'image/jpeg')
        
        logger.info(f"✓ Successfully served image via proxy: {clean_key} ({len(image_data)} bytes)")
        
        # Create a response with the image data
        resp = make_response(image_data)
        resp.headers['Content-Type'] = content_type
        resp.headers['Cache-Control'] = 'public, max-age=31536000'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        
        return resp
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"B2 ClientError for {clean_key}: {error_code}")
        
        if error_code == 'NoSuchKey':
            logger.warning(f"Image not found in B2: {clean_key}")
            # List objects in the bucket to see what's there
            try:
                objects = b2_client.list_objects_v2(Bucket=B2_CONFIG['BUCKET_NAME'], MaxKeys=10)
                if 'Contents' in objects:
                    logger.info(f"Files in bucket: {[obj['Key'] for obj in objects['Contents']]}")
            except Exception as list_error:
                logger.error(f"Error listing bucket: {list_error}")
            return send_file('static/placeholder.png')
        elif error_code == 'AccessDenied':
            logger.error(f"Access denied to B2 bucket for key: {clean_key}")
            return send_file('static/placeholder.png')
        else:
            logger.error(f"Error accessing image in B2: {e}")
            return send_file('static/placeholder.png')
            
    except Exception as e:
        logger.error(f"Unexpected error proxying image {s3_key}: {e}")
        return send_file('static/placeholder.png')

# ==================== PUBLIC ENDPOINTS ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint to get products - NO LOGIN REQUIRED"""
    if not data_store:
        return jsonify([]), 200
        
    try:
        data_store.load_all_data()
        products = data_store.products
        
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        products_copy = []
        for product in products:
            product_copy = product.copy()
            
            # Remove sensitive data
            product_copy.pop('buyPrice', None)
            product_copy.pop('createdBy', None)
            product_copy.pop('minSellPrice', None)
            product_copy.pop('maxSellPrice', None)
            
            # Use proxy URL for images
            if product.get('s3_key'):
                s3_key = product['s3_key']
                # Clean the s3_key
                if s3_key.startswith('/'):
                    s3_key = s3_key[1:]
                
                product_copy['image'] = f"/api/images/{s3_key}"
                product_copy['imageUrl'] = f"/api/images/{s3_key}"
            else:
                product_copy['image'] = '/static/placeholder.png'
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

@app.route('/api/public/health', methods=['GET'])
def public_health_check():
    """Public health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'app': 'Karanja Shoe Store',
        'b2_bucket': B2_CONFIG['BUCKET_NAME'] if B2_AVAILABLE else 'Not connected',
        'products': len(data_store.products) if data_store else 0,
        'storage_type': 'b2' if B2_AVAILABLE else 'local',
        'cross_device_sync': 'enabled' if B2_AVAILABLE else 'disabled'
    }), 200

@app.route('/api/public/b2/info', methods=['GET'])
def get_public_b2_info():
    """Public B2 info endpoint"""
    return jsonify({
        'bucketName': B2_CONFIG['BUCKET_NAME'],
        'created': B2_CONFIG['CREATED_DATE'],
        'cdn_url': B2_CONFIG['CDN_URL'],
        'stored_images': len(data_store.b2_images) if data_store else 0,
        'connected': B2_AVAILABLE,
        'storage_type': 'b2' if B2_AVAILABLE else 'local',
        'encryption': B2_CONFIG['ENCRYPTION']
    }), 200

# ==================== AUTHENTICATION ROUTES ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user with CONSTANT credentials only"""
    try:
        data = request.get_json()
        email = data.get('email', '').upper()
        password = data.get('password', '')
        
        logger.info(f"Login attempt - Email: {email}")
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        if email == CONSTANT_EMAIL and password == CONSTANT_PASSWORD:
            access_token = create_access_token(
                identity=CONSTANT_USER_ID,
                additional_claims={
                    'email': CONSTANT_EMAIL,
                    'name': CONSTANT_USER_NAME,
                    'role': CONSTANT_USER_ROLE
                }
            )
            
            logger.info(f"✓ Login successful for {CONSTANT_EMAIL}")
            
            return jsonify({
                'success': True,
                'token': access_token,
                'user': {
                    'id': CONSTANT_USER_ID,
                    'email': CONSTANT_EMAIL,
                    'name': CONSTANT_USER_NAME,
                    'role': CONSTANT_USER_ROLE
                }
            }), 200
        
        logger.warning(f"Login failed - Invalid credentials for {email}")
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user"""
    return jsonify({
        'id': CONSTANT_USER_ID,
        'email': CONSTANT_EMAIL,
        'name': CONSTANT_USER_NAME,
        'role': CONSTANT_USER_ROLE
    }), 200

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

# ==================== BACKBLAZE B2 UPLOAD ROUTE ====================

@app.route('/api/b2/upload', methods=['POST'])
@jwt_required()
def upload_to_b2():
    """Upload image to Backblaze B2 Private Bucket"""
    if not b2_client:
        logger.error("B2 client not available")
        return jsonify({'error': 'Backblaze B2 is not configured'}), 503
    
    try:
        # Ensure products folder exists
        try:
            b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key='products/.keep')
        except ClientError:
            # Create products folder if it doesn't exist
            b2_client.put_object(
                Bucket=B2_CONFIG['BUCKET_NAME'],
                Key='products/.keep',
                Body=b'',
                ContentType='text/plain'
            )
            logger.info("✓ Created products folder in B2")
        
        if 'image' not in request.files:
            logger.error("No image file in request")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({'error': 'No image selected'}), 400
        
        # Log file details
        logger.info(f"Received file: {file.filename}, Content-Type: {file.content_type}")
        
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        unique_filename = f"{timestamp}_{safe_filename}"
        s3_key = f"products/{unique_filename}"  # Store in products folder
        
        content_type = file.content_type
        if not content_type or content_type == 'application/octet-stream':
            content_type = mimetypes.guess_type(file.filename)[0] or 'image/jpeg'
        
        logger.info(f"Uploading to B2: {s3_key} ({content_type})")
        
        # Read the file data for verification
        file.seek(0)
        file_data = file.read()
        file_size = len(file_data)
        logger.info(f"File size: {file_size} bytes")
        
        if file_size == 0:
            logger.error("File is empty")
            return jsonify({'error': 'File is empty'}), 400
        
        # Reset file pointer for upload
        file.seek(0)
        
        # Upload to B2
        try:
            b2_client.upload_fileobj(
                file,
                B2_CONFIG['BUCKET_NAME'],
                s3_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'CacheControl': 'max-age=31536000',
                    'Metadata': {
                        'uploaded_by': get_jwt_identity(),
                        'original_filename': file.filename,
                        'uploaded_at': datetime.now().isoformat()
                    }
                }
            )
            logger.info(f"✓ Successfully uploaded image to B2: {s3_key}")
        except Exception as upload_error:
            logger.error(f"Upload failed: {upload_error}")
            return jsonify({'error': f'Upload failed: {str(upload_error)}'}), 500
        
        # Verify the upload was successful
        try:
            head_response = b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key=s3_key)
            logger.info(f"✓ Verified image exists in B2: {s3_key}")
            logger.info(f"  ETag: {head_response.get('ETag', 'N/A')}")
            logger.info(f"  Size: {head_response.get('ContentLength', 0)} bytes")
        except Exception as e:
            logger.error(f"Failed to verify image in B2: {e}")
            # Continue anyway - the upload might have succeeded
        
        # Generate proxy URL for immediate display
        proxy_url = f"/api/images/{s3_key}"
        
        # Store image record
        if data_store:
            image_record = {
                'id': str(uuid.uuid4()),
                's3_key': s3_key,
                'proxy_url': proxy_url,
                'fileName': unique_filename,
                'bucketId': B2_CONFIG['BUCKET_ID'],
                'bucketName': B2_CONFIG['BUCKET_NAME'],
                'uploadedAt': datetime.now().isoformat(),
                'fileSize': file_size,
                'contentType': content_type
            }
            data_store.b2_images.append(image_record)
            data_store.save_b2_images()
            logger.info(f"✓ Saved image record to B2 data store")
        
        # Return both url and image field for compatibility
        return jsonify({
            'success': True,
            'url': proxy_url,
            'proxy_url': proxy_url,
            'fileName': unique_filename,
            's3_key': s3_key,
            'image': proxy_url
        }), 200
        
    except Exception as e:
        logger.error(f"Error uploading to B2: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with image URLs"""
    if not data_store:
        return jsonify([]), 200
        
    try:
        data_store.load_all_data()
        products = data_store.products
        
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        products_copy = []
        for product in products:
            product_copy = product.copy()
            
            # Use proxy URL for images
            if product.get('s3_key'):
                s3_key = product['s3_key']
                # Clean the s3_key
                if s3_key.startswith('/'):
                    s3_key = s3_key[1:]
                
                product_copy['image'] = f"/api/images/{s3_key}"
                product_copy['imageUrl'] = f"/api/images/{s3_key}"
            else:
                product_copy['image'] = '/static/placeholder.png'
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
        
    try:
        name = request.form.get('name')
        price = request.form.get('price')
        description = request.form.get('description', '')
        category = request.form.get('category', 'Uncategorized')
        color = request.form.get('color', '')
        sku = request.form.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}")
        
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
        except:
            sizes = {}
        
        buy_price = request.form.get('buyPrice')
        min_sell_price = request.form.get('minSellPrice')
        max_sell_price = request.form.get('maxSellPrice')
        image_url = request.form.get('image_url')
        
        if not name:
            return jsonify({'error': 'Product name is required'}), 400
        
        if not max_sell_price and price:
            max_sell_price = price
        if not min_sell_price and price:
            min_sell_price = price
        
        if not max_sell_price:
            return jsonify({'error': 'Price is required'}), 400
        
        total_stock = 0
        for size, stock in sizes.items():
            try:
                total_stock += int(stock) if stock and int(stock) > 0 else 0
            except:
                pass
        
        # Extract s3_key from image_url
        s3_key = None
        if image_url:
            if '/api/images/' in image_url:
                s3_key = image_url.replace('/api/images/', '')
            elif 'backblazeb2.com' in image_url:
                # Extract from full B2 URL
                parsed = urlparse(image_url)
                path = parsed.path
                if '/file/' + B2_CONFIG['BUCKET_NAME'] + '/' in path:
                    s3_key = path.split('/file/' + B2_CONFIG['BUCKET_NAME'] + '/')[-1]
                else:
                    s3_key = path.lstrip('/')
            elif not image_url.startswith('/static/'):
                s3_key = image_url
            
            # Clean the s3_key
            if s3_key:
                s3_key = s3_key.lstrip('/')
                logger.info(f"Extracted s3_key: {s3_key}")
        
        product_id = int(datetime.now().timestamp() * 1000)
        
        product = {
            'id': product_id,
            'name': name.strip(),
            'price': float(max_sell_price) if max_sell_price else 0,
            'description': description.strip(),
            'sku': sku,
            'category': category,
            'color': color,
            'sizes': sizes,
            'buyPrice': float(buy_price) if buy_price else 0,
            'minSellPrice': float(min_sell_price) if min_sell_price else 0,
            'maxSellPrice': float(max_sell_price) if max_sell_price else 0,
            'totalStock': total_stock,
            'dateAdded': datetime.now().isoformat(),
            'lastUpdated': datetime.now().isoformat(),
            'createdBy': get_jwt_identity(),
            'storage': 'b2',
            'bucket': B2_CONFIG['BUCKET_NAME']
        }
        
        if s3_key:
            product['s3_key'] = s3_key
            # Use proxy URL for display
            product['image'] = f"/api/images/{s3_key}"
            product['image_source'] = 'b2'
        else:
            product['image'] = '/static/placeholder.png'
            product['image_source'] = 'placeholder'
        
        data_store.products.append(product)
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to save product to B2'}), 500
        
        # Create notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'New product added: {product["name"]}',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_notifications()
        
        logger.info(f"✓ Product created successfully: {name} (ID: {product_id})")
        
        return jsonify({
            'success': True,
            'message': 'Product uploaded successfully to B2!',
            'product': product
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update existing product"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
        
    try:
        data_store.load_all_data()
        
        product_index = None
        product = None
        for i, p in enumerate(data_store.products):
            if p['id'] == product_id:
                product_index = i
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        color = request.form.get('color')
        sku = request.form.get('sku')
        buy_price = request.form.get('buyPrice')
        min_sell_price = request.form.get('minSellPrice')
        max_sell_price = request.form.get('maxSellPrice')
        image_url = request.form.get('image_url')
        sizes_json = request.form.get('sizes')
        
        if name:
            product['name'] = name.strip()
        if description is not None:
            product['description'] = description.strip()
        if category:
            product['category'] = category
        if color is not None:
            product['color'] = color
        if sku:
            product['sku'] = sku
        if buy_price:
            product['buyPrice'] = float(buy_price)
        if min_sell_price:
            product['minSellPrice'] = float(min_sell_price)
        if max_sell_price:
            product['maxSellPrice'] = float(max_sell_price)
            product['price'] = float(max_sell_price)
        
        if sizes_json:
            try:
                sizes = json.loads(sizes_json)
                product['sizes'] = sizes
                
                total_stock = 0
                for size, stock in sizes.items():
                    try:
                        total_stock += int(stock) if stock and int(stock) > 0 else 0
                    except:
                        pass
                product['totalStock'] = total_stock
            except:
                pass
        
        if image_url:
            # Extract s3_key from image_url
            if '/api/images/' in image_url:
                s3_key = image_url.replace('/api/images/', '')
            elif 'backblazeb2.com' in image_url:
                parsed = urlparse(image_url)
                path = parsed.path
                if '/file/' + B2_CONFIG['BUCKET_NAME'] + '/' in path:
                    s3_key = path.split('/file/' + B2_CONFIG['BUCKET_NAME'] + '/')[-1]
                else:
                    s3_key = path.lstrip('/')
            elif not image_url.startswith('/static/'):
                s3_key = image_url
            else:
                s3_key = None
            
            if s3_key:
                s3_key = s3_key.lstrip('/')
                product['s3_key'] = s3_key
                # Use proxy URL
                product['image'] = f"/api/images/{s3_key}"
                product['image_source'] = 'b2'
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        data_store.products[product_index] = product
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to save product to B2'}), 500
        
        logger.info(f"✓ Product updated successfully: {product['name']} (ID: {product_id})")
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully in B2!',
            'product': product
        }), 200
        
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
        
    try:
        data_store.load_all_data()
        
        product = None
        new_products = []
        
        for p in data_store.products:
            if p['id'] == product_id:
                product = p
            else:
                new_products.append(p)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        data_store.cache['products'] = new_products
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to delete product from B2'}), 500
        
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Product deleted: {product["name"]}',
            'type': 'warning',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_notifications()
        
        logger.info(f"✓ Product deleted successfully: {product['name']} (ID: {product_id})")
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== DASHBOARD STATS ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    if not data_store:
        return jsonify({
            'totalProducts': 0,
            'totalStock': 0,
            'totalRevenue': 0,
            'totalProfit': 0,
            'todayRevenue': 0,
            'todayProfit': 0,
            'todayItems': 0,
            'salesCount': 0,
            'storage_type': 'local'
        }), 200
        
    try:
        data_store.load_all_data()
        products = data_store.products
        sales = data_store.sales
        
        total_products = len(products)
        total_stock = sum([p.get('totalStock', 0) for p in products])
        total_revenue = sum([s.get('totalAmount', 0) for s in sales])
        total_profit = sum([s.get('totalProfit', 0) for s in sales])
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_sales = [s for s in sales if s.get('timestamp', '').startswith(today)]
        today_revenue = sum([s.get('totalAmount', 0) for s in today_sales])
        today_profit = sum([s.get('totalProfit', 0) for s in today_sales])
        today_items = sum([s.get('quantity', 0) for s in today_sales])
        
        return jsonify({
            'totalProducts': total_products,
            'totalStock': total_stock,
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'todayRevenue': today_revenue,
            'todayProfit': today_profit,
            'todayItems': today_items,
            'salesCount': len(sales),
            'storage_type': 'b2',
            'bucket_name': B2_CONFIG['BUCKET_NAME']
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        return jsonify({
            'totalProducts': 0,
            'totalStock': 0,
            'totalRevenue': 0,
            'totalProfit': 0,
            'todayRevenue': 0,
            'todayProfit': 0,
            'todayItems': 0,
            'salesCount': 0,
            'storage_type': 'b2'
        }), 200

# ==================== SALES ROUTES ====================

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Record new sale"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
        
    try:
        data = request.get_json()
        
        product_id = data.get('productId')
        size = data.get('size')
        quantity = data.get('quantity')
        unit_price = data.get('unitPrice')
        customer_name = data.get('customerName', 'Walk-in Customer')
        notes = data.get('notes', '')
        is_bargain = data.get('isBargain', False)
        
        if not all([product_id, size, quantity, unit_price]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        data_store.load_all_data()
        
        product = None
        product_index = -1
        for i, p in enumerate(data_store.products):
            if p['id'] == product_id:
                product = p
                product_index = i
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        size_key = str(size)
        if size_key not in product['sizes'] or product['sizes'][size_key] < quantity:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        product['sizes'][size_key] -= quantity
        if product['sizes'][size_key] < 0:
            product['sizes'][size_key] = 0
        
        total_stock = 0
        for stock in product['sizes'].values():
            total_stock += stock if stock > 0 else 0
        product['totalStock'] = total_stock
        product['lastUpdated'] = datetime.now().isoformat()
        
        data_store.products[product_index] = product
        data_store.save_products()
        
        total_amount = unit_price * quantity
        total_cost = product['buyPrice'] * quantity
        total_profit = total_amount - total_cost
        
        sale = {
            'id': int(datetime.now().timestamp() * 1000),
            'productId': product_id,
            'productName': product['name'],
            'productSKU': product.get('sku', ''),
            'category': product.get('category', ''),
            'buyPrice': product['buyPrice'],
            'size': size,
            'quantity': quantity,
            'unitPrice': unit_price,
            'totalAmount': total_amount,
            'totalProfit': total_profit,
            'customerName': customer_name,
            'notes': notes,
            'isBargain': is_bargain,
            'timestamp': datetime.now().isoformat()
        }
        
        data_store.sales.append(sale)
        data_store.save_sales()
        
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Sale recorded: {product["name"]} ({quantity} × Size {size})',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_notifications()
        
        logger.info(f"✓ Sale recorded: {product['name']} - {quantity} x Size {size} @ {unit_price}")
        
        return jsonify({
            'success': True,
            'sale': sale
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating sale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales"""
    if not data_store:
        return jsonify([]), 200
        
    try:
        data_store.load_all_data()
        sales = data_store.sales
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(sales), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

# ==================== NOTIFICATION ROUTES ====================

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    if not data_store:
        return jsonify([]), 200
        
    try:
        data_store.load_all_data()
        notifications = data_store.notifications[:50]
        return jsonify(notifications), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_unread_notification_count():
    """Get unread notification count"""
    if not data_store:
        return jsonify({'count': 0}), 200
        
    try:
        data_store.load_all_data()
        unread_count = len([n for n in data_store.notifications if not n.get('read', False)])
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
        
    try:
        data_store.load_all_data()
        
        notification = None
        notification_index = -1
        for i, n in enumerate(data_store.notifications):
            if n['id'] == notification_id:
                notification = n
                notification_index = i
                break
        
        if notification:
            notification['read'] = True
            data_store.notifications[notification_index] = notification
            data_store.save_notifications()
            return jsonify({'success': True}), 200
        
        return jsonify({'error': 'Notification not found'}), 404
    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== B2 INFO ROUTES ====================

@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get Backblaze B2 bucket information"""
    return jsonify({
        'bucketId': B2_CONFIG['BUCKET_ID'],
        'bucketName': B2_CONFIG['BUCKET_NAME'],
        'endpoint': B2_CONFIG['ENDPOINT'],
        'region': B2_CONFIG['REGION'],
        'created': B2_CONFIG['CREATED_DATE'],
        'cdn_url': B2_CONFIG['CDN_URL'],
        'type': B2_CONFIG['TYPE'],
        'encryption': B2_CONFIG['ENCRYPTION'],
        'stored_images': len(data_store.b2_images) if data_store else 0,
        'connected': B2_AVAILABLE,
        'storage_type': 'b2' if B2_AVAILABLE else 'local'
    }), 200

# ==================== DEBUG ROUTES ====================

@app.route('/api/debug/test-upload', methods=['POST'])
@jwt_required()
def test_upload():
    """Test if we can upload to B2"""
    if not b2_client:
        return jsonify({'error': 'B2 not connected'}), 500
    
    try:
        # Ensure products folder exists
        try:
            b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key='products/.keep')
        except ClientError:
            b2_client.put_object(
                Bucket=B2_CONFIG['BUCKET_NAME'],
                Key='products/.keep',
                Body=b'',
                ContentType='text/plain'
            )
        
        # Try to upload a small test file
        test_key = f"products/test-file-{int(datetime.now().timestamp())}.txt"
        test_content = b"Test upload from Karanja Shoe Store - " + str(datetime.now()).encode()
        
        b2_client.put_object(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            Key=test_key,
            Body=test_content,
            ContentType='text/plain'
        )
        
        # Verify it exists
        head_response = b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key=test_key)
        
        return jsonify({
            'success': True,
            'message': 'Test upload successful',
            'key': test_key,
            'size': head_response.get('ContentLength')
        }), 200
    except Exception as e:
        logger.error(f"Test upload failed: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/api/debug/list-bucket', methods=['GET'])
@jwt_required()
def list_bucket():
    """List all files in the bucket"""
    if not b2_client:
        return jsonify({'error': 'B2 not connected'}), 500
    
    try:
        # List all objects in bucket
        all_files = []
        continuation_token = None
        
        while True:
            if continuation_token:
                response = b2_client.list_objects_v2(
                    Bucket=B2_CONFIG['BUCKET_NAME'],
                    ContinuationToken=continuation_token,
                    MaxKeys=1000
                )
            else:
                response = b2_client.list_objects_v2(
                    Bucket=B2_CONFIG['BUCKET_NAME'],
                    MaxKeys=1000
                )
            
            if 'Contents' in response:
                for obj in response['Contents']:
                    all_files.append({
                        'key': obj['Key'],
                        'size': obj['Size'],
                        'last_modified': obj['LastModified'].isoformat() if obj.get('LastModified') else None
                    })
            
            if response.get('IsTruncated'):
                continuation_token = response.get('NextContinuationToken')
            else:
                break
        
        # Get unique folders
        folders = set()
        for f in all_files:
            parts = f['key'].split('/')
            if len(parts) > 1:
                folders.add(parts[0])
        
        return jsonify({
            'success': True,
            'bucket': B2_CONFIG['BUCKET_NAME'],
            'files': all_files,
            'total_files': len(all_files),
            'folders': list(folders)
        }), 200
    except Exception as e:
        logger.error(f"Error listing bucket: {e}")
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/debug/b2-files', methods=['GET'])
@jwt_required()
def debug_b2_files():
    """Debug endpoint to list all files in B2 bucket"""
    if not b2_client:
        return jsonify({'error': 'B2 not connected'}), 500
    
    try:
        # List objects in bucket
        response = b2_client.list_objects_v2(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            MaxKeys=100
        )
        
        files = []
        if 'Contents' in response:
            for obj in response['Contents']:
                files.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat() if obj.get('LastModified') else None
                })
        
        # Also check the b2_images records
        images_records = []
        if data_store:
            images_records = data_store.b2_images
        
        return jsonify({
            'success': True,
            'bucket': B2_CONFIG['BUCKET_NAME'],
            'files_in_bucket': files,
            'file_count': len(files),
            'image_records': images_records,
            'record_count': len(images_records)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/debug/test-image/<path:s3_key>', methods=['GET'])
@jwt_required()
def debug_test_image(s3_key):
    """Test if an image exists in B2"""
    if not b2_client:
        return jsonify({'error': 'B2 not connected'}), 500
    
    try:
        # Clean the key
        if s3_key.startswith('/'):
            s3_key = s3_key[1:]
        
        # Try to get object metadata
        response = b2_client.head_object(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            Key=s3_key
        )
        
        return jsonify({
            'success': True,
            'key': s3_key,
            'exists': True,
            'metadata': {
                'content_length': response.get('ContentLength'),
                'content_type': response.get('ContentType'),
                'etag': response.get('ETag'),
                'last_modified': response.get('LastModified').isoformat() if response.get('LastModified') else None
            }
        }), 200
    except ClientError as e:
        if e.response['Error']['Code'] == 'NoSuchKey':
            return jsonify({
                'success': False,
                'key': s3_key,
                'exists': False,
                'error': 'File not found in B2'
            }), 404
        else:
            return jsonify({
                'success': False,
                'key': s3_key,
                'error': str(e)
            }), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
@jwt_required()
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'app': 'Karanja Shoe Store',
        'b2_bucket': B2_CONFIG['BUCKET_NAME'] if B2_AVAILABLE else 'Not connected',
        'b2_created': B2_CONFIG['CREATED_DATE'],
        'products': len(data_store.products) if data_store else 0,
        'sales': len(data_store.sales) if data_store else 0,
        'images': len(data_store.b2_images) if data_store else 0,
        'storage_type': 'b2' if B2_AVAILABLE else 'local',
        'cross_device_sync': 'enabled' if B2_AVAILABLE else 'disabled'
    }), 200

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        return jsonify({'error': 'Static file not found'}), 404

# ==================== STATIC PAGE ROUTES ====================

@app.route('/')
def index():
    """Serve index.html"""
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
        else:
            return jsonify({
                'message': 'Karanja Shoe Store API is running',
                'b2_bucket': B2_CONFIG['BUCKET_NAME'],
                'status': 'online',
                'storage_type': 'b2' if B2_AVAILABLE else 'local'
            }), 200
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Could not load index.html'}), 500

# ==================== CATCH-ALL ROUTE ====================

@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API routes"""
    if path.startswith('api/') or path.startswith('static/'):
        return jsonify({'error': 'Not found'}), 404
    
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
    except Exception as e:
        logger.error(f"Error serving index for path {path}: {e}")
    
    return jsonify({'error': 'Page not found'}), 404

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    if request.path.startswith('/static/'):
        return jsonify({'error': 'Static file not found'}), 404
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
    except:
        pass
    return jsonify({'error': 'Page not found'}), 404

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Authentication required', 'authenticated': False}), 401

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Internal server error: {e}")
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return index()

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 20MB'}), 413

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 70)
    logger.info("✓ KARANJA SHOE STORE - BACKBLAZE B2 INTEGRATION")
    logger.info("=" * 70)
    logger.info(f"  Bucket Name: {B2_CONFIG['BUCKET_NAME']}")
    logger.info(f"  Bucket ID: {B2_CONFIG['BUCKET_ID']}")
    logger.info(f"  Created: {B2_CONFIG['CREATED_DATE']}")
    logger.info(f"  Encryption: {B2_CONFIG['ENCRYPTION']}")
    logger.info(f"  Connection: {'✓ Connected' if B2_AVAILABLE else '✗ Failed'}")
    if data_store:
        logger.info(f"  Products: {len(data_store.products)}")
        logger.info(f"  Sales: {len(data_store.sales)}")
        logger.info(f"  Images: {len(data_store.b2_images)}")
    logger.info("=" * 70)
    logger.info("✓ CONSTANT LOGIN CREDENTIALS:")
    logger.info(f"  Email: {CONSTANT_EMAIL}")
    logger.info(f"  Password: {CONSTANT_PASSWORD}")
    logger.info("=" * 70)
    logger.info("✓ SERVER STARTED SUCCESSFULLY")
    logger.info(f"  URL: http://0.0.0.0:{port}")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=port, debug=True)
