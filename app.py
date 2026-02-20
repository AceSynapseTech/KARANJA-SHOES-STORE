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

# Create a simple placeholder image
placeholder_path = os.path.join('static', 'placeholder.png')
if not os.path.exists(placeholder_path):
    try:
        import base64
        transparent_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        with open(placeholder_path, 'wb') as f:
            f.write(base64.b64decode(transparent_png))
        logger.info("✓ Created placeholder image")
    except Exception as e:
        logger.warning(f"Could not create placeholder: {e}")

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
    
    # Use the KARANJASH Application Key (not Master Key)
    'ACCESS_KEY_ID': os.environ.get('B2_ACCESS_KEY_ID', '00320385f075dd50000000002'),
    'SECRET_ACCESS_KEY': os.environ.get('B2_SECRET_ACCESS_KEY', 'K0034O1CRh5jaFZRSwDBEf5e40lGJhY'),
    
    'TYPE': 'Private',
    'ENCRYPTION': 'Enabled',
    
    'DATA_PATHS': {
        'PRODUCTS': 'data/products.json',
        'SALES': 'data/sales.json',
        'NOTIFICATIONS': 'data/notifications.json',
        'SETTINGS': 'data/settings.json',
        'B2_IMAGES': 'data/b2_images.json'
    }
}

# Initialize Backblaze B2 client
B2_AVAILABLE = False
b2_client = None
data_store = None

try:
    logger.info("Attempting to connect to Backblaze B2...")
    logger.info(f"Endpoint: {B2_CONFIG['ENDPOINT']}")
    logger.info(f"Bucket: {B2_CONFIG['BUCKET_NAME']}")
    logger.info(f"Access Key ID: {B2_CONFIG['ACCESS_KEY_ID'][:10]}...")
    
    b2_client = boto3.client(
        's3',
        endpoint_url=f'https://{B2_CONFIG["ENDPOINT"]}',
        aws_access_key_id=B2_CONFIG['ACCESS_KEY_ID'],
        aws_secret_access_key=B2_CONFIG['SECRET_ACCESS_KEY'],
        config=Config(
            signature_version='s3v4',
            region_name=B2_CONFIG['REGION'],
            retries={'max_attempts': 3, 'mode': 'standard'}
        )
    )
    
    # Test the connection by listing buckets
    buckets = b2_client.list_buckets()
    logger.info(f"✓ Successfully connected to B2")
    logger.info(f"  Available buckets: {[b['Name'] for b in buckets['Buckets']]}")
    
    # Check if our bucket exists
    bucket_exists = False
    for bucket in buckets['Buckets']:
        if bucket['Name'] == B2_CONFIG['BUCKET_NAME']:
            bucket_exists = True
            break
    
    if bucket_exists:
        logger.info(f"✓ Bucket '{B2_CONFIG['BUCKET_NAME']}' found")
        B2_AVAILABLE = True
    else:
        logger.error(f"✗ Bucket '{B2_CONFIG['BUCKET_NAME']}' not found")
        B2_AVAILABLE = False
        
except Exception as e:
    logger.error(f"✗ Failed to connect to Backblaze B2: {e}")
    logger.error(traceback.format_exc())
    B2_AVAILABLE = False
    b2_client = None

# ==================== B2 DATA STORAGE MANAGER ====================
class B2DataStore:
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
            # Try to create a .keep file to ensure directory exists
            test_key = 'data/.keep'
            try:
                self.b2_client.head_object(Bucket=self.bucket_name, Key=test_key)
            except ClientError:
                # File doesn't exist, create it
                self.b2_client.put_object(
                    Bucket=self.bucket_name,
                    Key=test_key,
                    Body=b'',
                    ContentType='text/plain'
                )
                logger.info("✓ Created data directory in B2")
            return True
        except Exception as e:
            logger.error(f"Error ensuring data directory: {e}")
            return False
    
    def _read_json_from_b2(self, b2_key):
        """Read JSON data from B2"""
        if not self.b2_client:
            logger.error("B2 client not available")
            return {}
        
        try:
            logger.info(f"Reading from B2: {b2_key}")
            response = self.b2_client.get_object(
                Bucket=self.bucket_name,
                Key=b2_key
            )
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content) if content.strip() else {}
            logger.info(f"✓ Successfully read {b2_key} ({len(content)} bytes)")
            return data
            
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"File {b2_key} doesn't exist yet, will be created on first save")
                return {}
            logger.error(f"Error reading {b2_key}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error reading {b2_key}: {e}")
            return {}
    
    def _write_json_to_b2(self, b2_key, data):
        """Write JSON data to B2"""
        if not self.b2_client:
            logger.error("B2 client not available")
            return False
        
        try:
            json_str = json.dumps(data, indent=2, default=str)
            self.b2_client.put_object(
                Bucket=self.bucket_name,
                Key=b2_key,
                Body=json_str.encode('utf-8'),
                ContentType='application/json',
                CacheControl='no-cache'
            )
            logger.info(f"✓ Successfully wrote {b2_key} to B2 ({len(json_str)} bytes)")
            return True
        except Exception as e:
            logger.error(f"Error writing {b2_key}: {e}")
            return False
    
    def load_all_data(self):
        """Load all data from B2"""
        if not self.b2_client:
            logger.error("B2 client not available, cannot load data")
            return
        
        logger.info("Loading all data from Backblaze B2...")
        self._ensure_data_directory()
        
        # Load products
        products = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['PRODUCTS'])
        self.cache['products'] = products if isinstance(products, list) else []
        
        # Load sales
        sales = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SALES'])
        self.cache['sales'] = sales if isinstance(sales, list) else []
        
        # Load notifications
        notifications = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['NOTIFICATIONS'])
        self.cache['notifications'] = notifications if isinstance(notifications, list) else []
        
        # Load settings
        settings = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SETTINGS'])
        if isinstance(settings, dict):
            self.cache['settings'] = settings
        else:
            self.cache['settings'] = {
                'currency': 'KES',
                'low_stock_threshold': 3,
                'old_stock_days': 30,
                'theme': 'light',
                'storage': 'b2'
            }
        
        # Load images
        images = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'])
        self.cache['b2_images'] = images if isinstance(images, list) else []
        
        self.initialized = True
        logger.info("✓ All data loaded from Backblaze B2")
        logger.info(f"  Products: {len(self.cache['products'])}")
        logger.info(f"  Sales: {len(self.cache['sales'])}")
        logger.info(f"  Images: {len(self.cache['b2_images'])}")
        logger.info(f"  Notifications: {len(self.cache['notifications'])}")
    
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
    def b2_images(self):
        return self.cache.get('b2_images', [])
    
    def save_b2_images(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'], self.b2_images)

# Initialize Data Store
if not B2_AVAILABLE or not b2_client:
    logger.error("✗ Backblaze B2 connection failed. Please check your credentials.")
    logger.error("  Make sure you're using the correct Application Key (KARANJASH) not the Master Key")
    logger.error("  Application Key ID should start with '003'")
    data_store = None
else:
    data_store = B2DataStore(b2_client, B2_CONFIG['BUCKET_NAME'])
    logger.info("✓ Using Backblaze B2 for ALL data storage")

# ==================== EXTENSIONS ====================
CORS(app, resources={
    r"/api/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "expose_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    },
    r"/static/*": {
        "origins": ["*"]
    },
    r"/images/*": {
        "origins": ["*"]
    }
})
jwt = JWTManager(app)

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

# ==================== IMAGE HANDLING ====================

def extract_s3_key_from_url(url):
    """Extract S3 key from URL"""
    if not url:
        return None
    try:
        if '/images/' in url:
            return url.replace('/images/', '')
        return url
    except Exception as e:
        logger.error(f"Error extracting S3 key: {e}")
        return None

@app.route('/images/<path:s3_key>')
@optional_jwt_required()
def serve_image(s3_key):
    """Serve image from Backblaze B2"""
    if not b2_client:
        logger.warning("B2 client not available, serving placeholder")
        return send_file('static/placeholder.png')
    
    logger.info(f"Attempting to serve image: {s3_key}")
    
    try:
        response = b2_client.get_object(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            Key=s3_key
        )
        
        image_data = response['Body'].read()
        content_type = response.get('ContentType', 'image/jpeg')
        
        resp = make_response(image_data)
        resp.headers['Content-Type'] = content_type
        resp.headers['Cache-Control'] = 'public, max-age=31536000'
        resp.headers['Access-Control-Allow-Origin'] = '*'
        
        logger.info(f"✓ Successfully served image: {s3_key} ({len(image_data)} bytes)")
        return resp
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        logger.error(f"B2 error for {s3_key}: {error_code}")
        return send_file('static/placeholder.png')
    except Exception as e:
        logger.error(f"Error serving image: {e}")
        return send_file('static/placeholder.png')

@app.route('/api/upload', methods=['POST'])
@jwt_required()
def upload_image():
    """Upload image to Backblaze B2"""
    if not b2_client or not data_store:
        return jsonify({'error': 'Backblaze B2 is not available'}), 503
    
    logger.info("=== IMAGE UPLOAD REQUEST ===")
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        logger.info(f"File received: {file.filename}")
        
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        filename = f"{timestamp}_{safe_filename}"
        s3_key = f"products/{filename}"
        
        # Read file data
        file.seek(0)
        file_data = file.read()
        file_size = len(file_data)
        
        logger.info(f"Uploading to B2: {s3_key} ({file_size} bytes)")
        
        # Upload to B2
        b2_client.put_object(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            Key=s3_key,
            Body=file_data,
            ContentType=file.content_type or 'image/jpeg',
            CacheControl='max-age=31536000'
        )
        
        logger.info(f"✓ Successfully uploaded to B2")
        
        # Verify upload
        try:
            b2_client.head_object(Bucket=B2_CONFIG['BUCKET_NAME'], Key=s3_key)
            logger.info(f"✓ Verified image exists in B2")
        except Exception as e:
            logger.error(f"Failed to verify upload: {e}")
        
        # Create image URL
        image_url = f"/images/{s3_key}"
        
        # Store image record in B2
        image_record = {
            'id': str(uuid.uuid4()),
            's3_key': s3_key,
            'url': image_url,
            'filename': filename,
            'original_filename': file.filename,
            'file_size': file_size,
            'content_type': file.content_type,
            'uploaded_at': datetime.now().isoformat(),
            'uploaded_by': get_jwt_identity()
        }
        
        data_store.b2_images.append(image_record)
        data_store.save_b2_images()
        
        logger.info(f"✓ Image record saved, URL: {image_url}")
        
        return jsonify({
            'success': True,
            'url': image_url,
            's3_key': s3_key,
            'filename': filename
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== AUTHENTICATION ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login with constant credentials"""
    try:
        data = request.get_json()
        email = data.get('email', '').upper().strip()
        password = data.get('password', '').strip()
        
        if email == CONSTANT_EMAIL and password == CONSTANT_PASSWORD:
            access_token = create_access_token(
                identity=CONSTANT_USER_ID,
                additional_claims={
                    'email': CONSTANT_EMAIL,
                    'name': CONSTANT_USER_NAME,
                    'role': CONSTANT_USER_ROLE
                }
            )
            
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
        
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user"""
    return jsonify({
        'id': CONSTANT_USER_ID,
        'email': CONSTANT_EMAIL,
        'name': CONSTANT_USER_NAME,
        'role': CONSTANT_USER_ROLE
    }), 200

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    return jsonify({'success': True}), 200

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
    
    try:
        data_store.load_all_data()
        return jsonify(data_store.products), 200
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Get products for public view"""
    if not data_store:
        return jsonify([]), 200
    
    try:
        data_store.load_all_data()
        products = []
        for p in data_store.products:
            p_copy = {
                'id': p.get('id'),
                'name': p.get('name'),
                'category': p.get('category'),
                'color': p.get('color'),
                'sku': p.get('sku'),
                'sizes': p.get('sizes', {}),
                'totalStock': p.get('totalStock', 0),
                'description': p.get('description', ''),
                'image': p.get('image', '/static/placeholder.png'),
                'price': p.get('maxSellPrice') or p.get('price', 0),
                'minSellPrice': p.get('minSellPrice', 0),
                'maxSellPrice': p.get('maxSellPrice', p.get('price', 0)),
                'dateAdded': p.get('dateAdded')
            }
            products.append(p_copy)
        
        return jsonify(products), 200
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
    
    try:
        logger.info("=== CREATE PRODUCT ===")
        
        # Get form data
        name = request.form.get('name')
        category = request.form.get('category')
        color = request.form.get('color')
        sku = request.form.get('sku')
        price = request.form.get('price')
        buy_price = request.form.get('buyPrice')
        min_sell = request.form.get('minSellPrice')
        max_sell = request.form.get('maxSellPrice')
        description = request.form.get('description', '')
        image_url = request.form.get('image_url')
        
        # Get sizes
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
        except:
            sizes = {}
        
        if not name:
            return jsonify({'error': 'Product name is required'}), 400
        
        if not sku:
            sku = f"KS-{uuid.uuid4().hex[:8].upper()}"
        
        # Calculate total stock
        total_stock = 0
        for size, stock in sizes.items():
            try:
                if stock and int(stock) > 0:
                    total_stock += int(stock)
            except:
                pass
        
        product_id = int(datetime.now().timestamp() * 1000)
        
        product = {
            'id': product_id,
            'name': name,
            'category': category,
            'color': color,
            'sku': sku,
            'price': float(price) if price else 0,
            'buyPrice': float(buy_price) if buy_price else 0,
            'minSellPrice': float(min_sell) if min_sell else (float(price) if price else 0),
            'maxSellPrice': float(max_sell) if max_sell else (float(price) if price else 0),
            'sizes': sizes,
            'totalStock': total_stock,
            'description': description,
            'image': image_url if image_url else '/static/placeholder.png',
            'dateAdded': datetime.now().isoformat(),
            'lastUpdated': datetime.now().isoformat(),
            'createdBy': get_jwt_identity()
        }
        
        # Extract s3_key if image is from our upload
        if image_url and image_url.startswith('/images/'):
            product['s3_key'] = image_url.replace('/images/', '')
        
        data_store.products.append(product)
        save_success = data_store.save_products()
        
        if not save_success:
            return jsonify({'error': 'Failed to save product to B2'}), 500
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'New product: {name}',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_notifications()
        
        return jsonify({
            'success': True,
            'product': product
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update product"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
    
    try:
        data_store.load_all_data()
        
        for i, p in enumerate(data_store.products):
            if p['id'] == product_id:
                # Update fields
                if request.form.get('name'):
                    p['name'] = request.form.get('name')
                if request.form.get('category'):
                    p['category'] = request.form.get('category')
                if request.form.get('color'):
                    p['color'] = request.form.get('color')
                if request.form.get('sku'):
                    p['sku'] = request.form.get('sku')
                if request.form.get('price'):
                    p['price'] = float(request.form.get('price'))
                if request.form.get('buyPrice'):
                    p['buyPrice'] = float(request.form.get('buyPrice'))
                if request.form.get('minSellPrice'):
                    p['minSellPrice'] = float(request.form.get('minSellPrice'))
                if request.form.get('maxSellPrice'):
                    p['maxSellPrice'] = float(request.form.get('maxSellPrice'))
                if request.form.get('description') is not None:
                    p['description'] = request.form.get('description')
                if request.form.get('image_url'):
                    p['image'] = request.form.get('image_url')
                    if request.form.get('image_url').startswith('/images/'):
                        p['s3_key'] = request.form.get('image_url').replace('/images/', '')
                
                # Update sizes
                if request.form.get('sizes'):
                    try:
                        sizes = json.loads(request.form.get('sizes'))
                        p['sizes'] = sizes
                        
                        total_stock = 0
                        for size, stock in sizes.items():
                            try:
                                if stock and int(stock) > 0:
                                    total_stock += int(stock)
                            except:
                                pass
                        p['totalStock'] = total_stock
                    except:
                        pass
                
                p['lastUpdated'] = datetime.now().isoformat()
                
                save_success = data_store.save_products()
                
                if not save_success:
                    return jsonify({'error': 'Failed to save product to B2'}), 500
                
                return jsonify({
                    'success': True,
                    'product': p
                }), 200
        
        return jsonify({'error': 'Product not found'}), 404
        
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
        
        for i, p in enumerate(data_store.products):
            if p['id'] == product_id:
                product_name = p['name']
                del data_store.products[i]
                save_success = data_store.save_products()
                
                if not save_success:
                    return jsonify({'error': 'Failed to delete product from B2'}), 500
                
                # Add notification
                notification = {
                    'id': int(datetime.now().timestamp() * 1000),
                    'message': f'Product deleted: {product_name}',
                    'type': 'warning',
                    'timestamp': datetime.now().isoformat(),
                    'read': False
                }
                data_store.notifications.insert(0, notification)
                data_store.save_notifications()
                
                return jsonify({'success': True}), 200
        
        return jsonify({'error': 'Product not found'}), 404
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== SALES ROUTES ====================

@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales"""
    if not data_store:
        return jsonify([]), 200
    
    try:
        data_store.load_all_data()
        sales = sorted(data_store.sales, key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(sales), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Create new sale"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
    
    try:
        data = request.get_json()
        
        product_id = data.get('productId')
        size = str(data.get('size'))
        quantity = int(data.get('quantity', 1))
        unit_price = float(data.get('unitPrice'))
        customer = data.get('customerName', 'Walk-in Customer')
        is_bargain = data.get('isBargain', False)
        
        if not all([product_id, size, quantity, unit_price]):
            return jsonify({'error': 'Missing required fields'}), 400
        
        data_store.load_all_data()
        
        # Find product
        product = None
        product_index = -1
        for i, p in enumerate(data_store.products):
            if p['id'] == product_id:
                product = p
                product_index = i
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        sizes = product.get('sizes', {})
        if size not in sizes or sizes[size] < quantity:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Update stock
        sizes[size] -= quantity
        product['sizes'] = sizes
        product['totalStock'] = sum([s for s in sizes.values() if s > 0])
        product['lastUpdated'] = datetime.now().isoformat()
        
        # Calculate totals
        total_amount = unit_price * quantity
        buy_price = product.get('buyPrice', 0)
        total_profit = total_amount - (buy_price * quantity)
        
        # Create sale record
        sale = {
            'id': int(datetime.now().timestamp() * 1000),
            'productId': product_id,
            'productName': product['name'],
            'productSKU': product.get('sku', ''),
            'category': product.get('category', ''),
            'buyPrice': buy_price,
            'size': size,
            'quantity': quantity,
            'unitPrice': unit_price,
            'totalAmount': total_amount,
            'totalProfit': total_profit,
            'customerName': customer,
            'isBargain': is_bargain,
            'notes': data.get('notes', ''),
            'timestamp': datetime.now().isoformat()
        }
        
        data_store.sales.append(sale)
        save_sales_success = data_store.save_sales()
        save_products_success = data_store.save_products()
        
        if not save_sales_success or not save_products_success:
            return jsonify({'error': 'Failed to save sale to B2'}), 500
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Sale: {product["name"]} - {quantity} x Size {size}',
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
            'salesCount': 0
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
            'salesCount': len(sales)
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
            'salesCount': 0
        }), 200

# ==================== NOTIFICATION ROUTES ====================

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get notifications"""
    if not data_store:
        return jsonify([]), 200
    
    try:
        data_store.load_all_data()
        return jsonify(data_store.notifications[:50]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_notification_count():
    """Get unread notification count"""
    if not data_store:
        return jsonify({'count': 0}), 200
    
    try:
        data_store.load_all_data()
        unread = len([n for n in data_store.notifications if not n.get('read', False)])
        return jsonify({'count': unread}), 200
    except Exception as e:
        logger.error(f"Error getting notification count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    if not data_store:
        return jsonify({'error': 'Data store not available'}), 503
    
    try:
        data_store.load_all_data()
        
        for n in data_store.notifications:
            if n['id'] == notification_id:
                n['read'] = True
                save_success = data_store.save_notifications()
                
                if not save_success:
                    return jsonify({'error': 'Failed to save to B2'}), 500
                
                return jsonify({'success': True}), 200
        
        return jsonify({'error': 'Notification not found'}), 404
        
    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== B2 INFO ====================

@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get B2 info"""
    return jsonify({
        'bucket_name': B2_CONFIG['BUCKET_NAME'],
        'connected': B2_AVAILABLE,
        'images_count': len(data_store.b2_images) if data_store else 0
    }), 200

@app.route('/api/public/b2/info', methods=['GET'])
def get_public_b2_info():
    """Get public B2 info"""
    return jsonify({
        'bucket_name': B2_CONFIG['BUCKET_NAME'],
        'connected': B2_AVAILABLE,
        'images_count': len(data_store.b2_images) if data_store else 0
    }), 200

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'b2_connected': B2_AVAILABLE,
        'products': len(data_store.products) if data_store else 0,
        'sales': len(data_store.sales) if data_store else 0,
        'images': len(data_store.b2_images) if data_store else 0
    }), 200

@app.route('/api/public/health', methods=['GET'])
def public_health_check():
    """Public health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'b2_connected': B2_AVAILABLE
    }), 200

# ==================== STATIC FILES ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except:
        return jsonify({'error': 'File not found'}), 404

# ==================== MAIN PAGE ====================

@app.route('/')
def index():
    """Serve index.html"""
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
        return jsonify({'message': 'Karanja Shoe Store API'})
    except:
        return jsonify({'message': 'Karanja Shoe Store API'})

@app.route('/<path:path>')
def catch_all(path):
    """Catch all routes"""
    if path.startswith('api/') or path.startswith('static/') or path.startswith('images/'):
        return jsonify({'error': 'Not found'}), 404
    
    if os.path.exists('index.html'):
        return send_file('index.html')
    
    return jsonify({'error': 'Not found'}), 404

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def too_large_error(error):
    return jsonify({'error': 'File too large. Maximum size is 20MB'}), 413

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    print("\n" + "=" * 70)
    print("🚀 KARANJA SHOE STORE - BACKBLAZE B2 INTEGRATION")
    print("=" * 70)
    print(f"\n📦 Backblaze B2 Status:")
    print(f"   • Connected: {'✅ YES' if B2_AVAILABLE else '❌ NO'}")
    print(f"   • Bucket: {B2_CONFIG['BUCKET_NAME']}")
    print(f"   • Bucket ID: {B2_CONFIG['BUCKET_ID']}")
    print(f"   • Endpoint: {B2_CONFIG['ENDPOINT']}")
    
    if data_store:
        print(f"\n📊 Data Store:")
        print(f"   • Products: {len(data_store.products)}")
        print(f"   • Sales: {len(data_store.sales)}")
        print(f"   • Images: {len(data_store.b2_images)}")
    
    print(f"\n🔐 Login Credentials:")
    print(f"   • Email: {CONSTANT_EMAIL}")
    print(f"   • Password: {CONSTANT_PASSWORD}")
    
    print(f"\n🌐 Server:")
    print(f"   • URL: http://0.0.0.0:{port}")
    print("=" * 70 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)
