from flask import Flask, request, jsonify, send_file, send_from_directory, make_response
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)  # Extended token expiry
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['STATIC_FOLDER'] = 'static'

# Create static folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

# ==================== CONSTANT LOGIN CREDENTIALS ====================
# THESE CREDENTIALS WILL NEVER CHANGE
CONSTANT_EMAIL = "KARANJASHOESTORE@GMAIL.COM"
CONSTANT_PASSWORD = "0726539216"
CONSTANT_USER_ID = "1"
CONSTANT_USER_NAME = "Karanja Shoe Store"
CONSTANT_USER_ROLE = "admin"

# ==================== BACKBLAZE B2 CONFIGURATION ====================
B2_CONFIG = {
    # BUCKET INFORMATION
    'BUCKET_NAME': os.environ.get('B2_BUCKET_NAME', 'karanjashoesstore'),
    'BUCKET_ID': os.environ.get('B2_BUCKET_ID', '9240b308551f401795cd0d15'),
    'ENDPOINT': os.environ.get('B2_ENDPOINT', 's3.eu-central-003.backblazeb2.com'),
    'REGION': os.environ.get('B2_REGION', 'eu-central-003'),
    'CDN_URL': os.environ.get('B2_CDN_URL', 'https://f005.backblazeb2.com/file/karanjashoesstore'),
    'CREATED_DATE': 'February 9, 2026',
    
    # MASTER APPLICATION KEY
    'ACCESS_KEY_ID': os.environ.get('B2_ACCESS_KEY_ID', '20385f075dd5'),
    'SECRET_ACCESS_KEY': os.environ.get('B2_SECRET_ACCESS_KEY', '00320385f075dd50000000001'),
    
    # BUCKET STATUS
    'TYPE': 'Private',
    
    # DATA STORAGE PATHS IN B2
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
    B2_AVAILABLE = True
except Exception as e:
    logger.error(f"✗ Failed to initialize B2 client: {e}")
    B2_AVAILABLE = False
    b2_client = None

# ==================== EXTENSIONS ====================
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True,
        "max_age": 3600
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
    """Decorator that doesn't require JWT but will set current_user if valid"""
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
    """All data stored in Backblaze B2 - Fixed version with proper error handling"""
    
    def __init__(self, b2_client, bucket_name):
        self.b2_client = b2_client
        self.bucket_name = bucket_name
        self.cache = {}
        self.initialized = False
        self.load_all_data()
    
    def _ensure_data_directory(self):
        """Ensure the data directory exists in B2"""
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
        """Read JSON data from B2 bucket"""
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
        """Write JSON data to B2 bucket"""
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
        """Load all data from B2 into cache"""
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
    raise Exception("Backblaze B2 connection failed. Check your credentials and bucket permissions.")

data_store = B2DataStore(b2_client, B2_CONFIG['BUCKET_NAME'])
logger.info("✓ Using Backblaze B2 for ALL data storage")

# ==================== PUBLIC ENDPOINTS (NO JWT REQUIRED) ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint to get products - NO LOGIN REQUIRED"""
    try:
        data_store.load_all_data()
        products = data_store.products
        
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        products_copy = []
        for product in products:
            product_copy = product.copy()
            product_copy.pop('buyPrice', None)
            product_copy.pop('createdBy', None)
            product_copy.pop('minSellPrice', None)
            product_copy.pop('maxSellPrice', None)
            
            if product.get('s3_key'):
                fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
                if fresh_url:
                    product_copy['image'] = fresh_url
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

@app.route('/api/public/health', methods=['GET'])
def public_health_check():
    """Public health check endpoint - NO LOGIN REQUIRED"""
    try:
        data_store.load_all_data()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'app': 'Karanja Shoe Store',
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'products': len(data_store.products),
            'sales': len(data_store.sales),
            'storage_type': 'b2',
            'cross_device_sync': 'enabled'
        }), 200
    except Exception as e:
        return jsonify({'status': 'degraded', 'error': str(e)}), 200

@app.route('/api/public/b2/info', methods=['GET'])
def get_public_b2_info():
    """Public B2 info endpoint - NO LOGIN REQUIRED"""
    try:
        return jsonify({
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'created': B2_CONFIG['CREATED_DATE'],
            'cdn_url': B2_CONFIG['CDN_URL'],
            'stored_images': len(data_store.b2_images),
            'connected': True,
            'storage_type': 'b2'
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== AUTHENTICATION ROUTES (CONSTANT CREDENTIALS) ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user with CONSTANT credentials only"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        logger.info(f"Login attempt - Email: {email}")
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        # ONLY check against constant credentials
        if email.upper() == CONSTANT_EMAIL and password == CONSTANT_PASSWORD:
            # Generate JWT token
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
        
        # If credentials don't match constant ones, return error
        logger.warning(f"Login failed - Invalid credentials for {email}")
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user - always returns constant user"""
    try:
        # Always return the constant user
        return jsonify({
            'id': CONSTANT_USER_ID,
            'email': CONSTANT_EMAIL,
            'name': CONSTANT_USER_NAME,
            'role': CONSTANT_USER_ROLE
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user - client should discard token"""
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

# ==================== BACKBLAZE B2 UPLOAD ROUTE ====================

@app.route('/api/b2/upload', methods=['POST'])
@jwt_required()
def upload_to_b2():
    """Upload image to Backblaze B2 Private Bucket - JWT REQUIRED"""
    if not b2_client:
        return jsonify({'error': 'Backblaze B2 is not configured'}), 503
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        unique_filename = f"{timestamp}_{safe_filename}"
        s3_key = f"products/{unique_filename}"
        
        content_type = file.content_type
        if not content_type:
            content_type = mimetypes.guess_type(file.filename)[0] or 'image/jpeg'
        
        file.seek(0)
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
        
        signed_url = generate_signed_url(s3_key, expiration=604800)
        
        image_record = {
            'id': str(uuid.uuid4()),
            'signed_url': signed_url,
            's3_key': s3_key,
            'fileName': unique_filename,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'uploadedAt': datetime.now().isoformat()
        }
        
        data_store.b2_images.append(image_record)
        data_store.save_b2_images()
        
        return jsonify({
            'success': True,
            'url': signed_url,
            'signed_url': signed_url,
            'fileName': unique_filename,
            's3_key': s3_key
        }), 200
        
    except Exception as e:
        logger.error(f"Error uploading to B2: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== BACKBLAZE B2 HELPER FUNCTIONS ====================

def generate_signed_url(s3_key, expiration=604800):
    """Generate a pre-signed URL for private B2 bucket access"""
    if not b2_client or not s3_key:
        return None
    try:
        url = b2_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': B2_CONFIG['BUCKET_NAME'],
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        return url
    except Exception as e:
        logger.error(f"Error generating signed URL: {e}")
        return None

def extract_s3_key_from_url(url):
    """Extract S3 key from B2 URL"""
    if not url:
        return None
    try:
        if B2_CONFIG['CDN_URL'] in url:
            return url.replace(f"{B2_CONFIG['CDN_URL']}/", '')
        if 'backblazeb2.com' in url:
            import re
            match = re.search(r'products/[^?]+', url)
            if match:
                return match.group(0)
        if url.startswith('products/'):
            return url
    except Exception as e:
        logger.error(f"Error extracting S3 key: {e}")
    return None

# ==================== PRODUCT ROUTES (JWT REQUIRED) ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with fresh signed URLs - JWT REQUIRED"""
    try:
        data_store.load_all_data()
        products = data_store.products
        
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        products_copy = []
        for product in products:
            product_copy = product.copy()
            if product.get('s3_key'):
                fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
                if fresh_url:
                    product_copy['image'] = fresh_url
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product - JWT REQUIRED"""
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
        
        s3_key = None
        if image_url and 'backblazeb2.com' in image_url:
            s3_key = extract_s3_key_from_url(image_url)
        
        signed_url = None
        if s3_key:
            signed_url = generate_signed_url(s3_key, expiration=604800)
        
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
        
        if signed_url:
            product['image'] = signed_url
            product['s3_key'] = s3_key
            product['image_source'] = 'b2'
        else:
            product['image'] = '/static/placeholder.png'
            product['image_source'] = 'placeholder'
        
        data_store.products.append(product)
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to save product to B2'}), 500
        
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'New product added: {product["name"]}',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_notifications()
        
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
    """Update existing product - JWT REQUIRED"""
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
            s3_key = extract_s3_key_from_url(image_url)
            if s3_key:
                product['s3_key'] = s3_key
                product['image'] = generate_signed_url(s3_key, expiration=604800)
                product['image_source'] = 'b2'
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        data_store.products[product_index] = product
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to save product to B2'}), 500
        
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
    """Delete product - JWT REQUIRED"""
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
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files with caching"""
    try:
        response = make_response(send_from_directory('static', filename))
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        return jsonify({'error': 'Static file not found'}), 404

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    """Serve uploaded files with caching"""
    try:
        response = make_response(send_from_directory('static/uploads', filename))
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        logger.error(f"Error serving upload {filename}: {e}")
        return jsonify({'error': 'Uploaded file not found'}), 404

# ==================== DASHBOARD STATS (JWT REQUIRED) ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics - JWT REQUIRED"""
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

# ==================== SALES ROUTES (JWT REQUIRED) ====================

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Record new sale - JWT REQUIRED"""
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
    """Get all sales - JWT REQUIRED"""
    try:
        data_store.load_all_data()
        sales = data_store.sales
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(sales), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

# ==================== NOTIFICATION ROUTES (JWT REQUIRED) ====================

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications - JWT REQUIRED"""
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
    """Get unread notification count - JWT REQUIRED"""
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
    """Mark notification as read - JWT REQUIRED"""
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

# ==================== B2 INFO ROUTES (JWT REQUIRED) ====================

@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get Backblaze B2 bucket information - JWT REQUIRED"""
    try:
        return jsonify({
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'region': B2_CONFIG['REGION'],
            'created': B2_CONFIG['CREATED_DATE'],
            'cdn_url': B2_CONFIG['CDN_URL'],
            'type': B2_CONFIG['TYPE'],
            'stored_images': len(data_store.b2_images),
            'connected': True,
            'storage_type': 'b2'
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
@jwt_required()
def health_check():
    """Health check endpoint - JWT REQUIRED"""
    try:
        data_store.load_all_data()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'app': 'Karanja Shoe Store',
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'b2_created': B2_CONFIG['CREATED_DATE'],
            'products': len(data_store.products),
            'sales': len(data_store.sales),
            'images': len(data_store.b2_images),
            'storage_type': 'b2',
            'cross_device_sync': 'enabled'
        }), 200
    except Exception as e:
        return jsonify({'status': 'degraded', 'error': str(e)}), 200

# ==================== STATIC PAGE ROUTES ====================

@app.route('/')
def index():
    """Serve index.html with proper caching headers to prevent refresh loop"""
    try:
        if os.path.exists('index.html'):
            response = make_response(send_file('index.html'))
            response.headers['Cache-Control'] = 'public, max-age=3600'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        else:
            return jsonify({
                'message': 'Karanja Shoe Store API is running',
                'b2_bucket': B2_CONFIG['BUCKET_NAME'],
                'products': len(data_store.products),
                'status': 'online',
                'storage_type': 'b2',
                'cross_device_sync': 'enabled'
            }), 200
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Could not load index.html'}), 500

# ==================== CATCH-ALL ROUTE ====================

@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API routes with proper headers"""
    if path.startswith('api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    if path.startswith('static/'):
        return jsonify({'error': 'Static file not found'}), 404
    
    try:
        if os.path.exists('index.html'):
            response = make_response(send_file('index.html'))
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response
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
            response = make_response(send_file('index.html'))
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response
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

# ==================== INITIALIZE SAMPLE DATA ====================

def init_sample_data():
    """Initialize sample data if no products exist"""
    try:
        if len(data_store.products) == 0:
            placeholder_path = os.path.join('static', 'placeholder.png')
            if not os.path.exists(placeholder_path):
                os.makedirs('static', exist_ok=True)
                try:
                    from PIL import Image, ImageDraw
                    img = Image.new('RGB', (300, 300), color=(102, 126, 234))
                    draw = ImageDraw.Draw(img)
                    draw.text((150, 150), "No Image", fill="white", anchor="mm")
                    img.save(placeholder_path)
                    logger.info("✓ Created placeholder image")
                except ImportError:
                    logger.warning("⚠ PIL not installed, skipping placeholder creation")
            
            notification = {
                'id': int(datetime.now().timestamp() * 1000),
                'message': f'Welcome to Karanja Shoe Store! ALL data stored in Backblaze B2 bucket: {B2_CONFIG["BUCKET_NAME"]}',
                'type': 'info',
                'timestamp': datetime.now().isoformat(),
                'read': False
            }
            data_store.notifications.insert(0, notification)
            data_store.save_notifications()
            logger.info(f"✓ Sample data initialized in B2 bucket: {B2_CONFIG['BUCKET_NAME']}")
    except Exception as e:
        logger.error(f"Error initializing data: {e}")

# Initialize sample data
init_sample_data()

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 70)
    logger.info("✓ BACKBLAZE B2 CLOUD STORAGE - ALL DATA SYNCED ACROSS DEVICES")
    logger.info(f"  Bucket Name: {B2_CONFIG['BUCKET_NAME']}")
    logger.info(f"  Bucket ID: {B2_CONFIG['BUCKET_ID']}")
    logger.info(f"  Created: {B2_CONFIG['CREATED_DATE']}")
    logger.info(f"  Products: {len(data_store.products)}")
    logger.info(f"  Sales: {len(data_store.sales)}")
    logger.info(f"  Images: {len(data_store.b2_images)}")
    logger.info("=" * 70)
    logger.info("✓ CONSTANT LOGIN CREDENTIALS (NEVER CHANGE):")
    logger.info(f"  Email: {CONSTANT_EMAIL}")
    logger.info(f"  Password: {CONSTANT_PASSWORD}")
    logger.info("=" * 70)
    logger.info("✓ CROSS-DEVICE SYNC ENABLED - Data is the same on phone, tablet, and PC")
    logger.info("=" * 70)
    logger.info("✓ PUBLIC ENDPOINTS AVAILABLE:")
    logger.info("  - GET  /api/public/products")
    logger.info("  - GET  /api/public/health")
    logger.info("  - GET  /api/public/b2/info")
    logger.info("  - POST /api/auth/login")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=port, debug=False)
