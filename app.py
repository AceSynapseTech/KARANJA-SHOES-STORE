from flask import Flask, request, jsonify, send_file, render_template_string, send_from_directory
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import json
import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from werkzeug.utils import secure_filename
import uuid
from decimal import Decimal
import csv
import io
from functools import wraps
import mimetypes
import logging
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['STATIC_FOLDER'] = 'static'
app.config['STATIC_URL'] = '/static'

# Create static folders
os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
os.makedirs(os.path.join('static', 'products'), exist_ok=True)

# ==================== BACKBLAZE B2 CONFIGURATION - JANUARY 22, 2026 ====================
B2_CONFIG = {
    # BUCKET INFORMATION
    'BUCKET_NAME': 'karanja-shoe-store',
    'BUCKET_ID': 'e318a1c1ef68e53f99b8001c',
    'ENDPOINT': 's3.eu-central-003.backblazeb2.com',
    'REGION': 'eu-central-003',
    'CDN_URL': 'https://f005.backblazeb2.com/file/karanja-shoe-store',
    'CREATED_DATE': 'January 22, 2026',
    
    # MASTER APPLICATION KEY
    'ACCESS_KEY_ID': '3811f85f980c',
    'SECRET_ACCESS_KEY': 'K003RvlqkCMQKDtV5Dzgk9qDcDj6fN8',
    
    # BUCKET STATUS
    'TYPE': 'Private',
    'CURRENT_FILES': 14,
    'CURRENT_SIZE': '24.3 MB',
    
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
        'B2_IMAGES': 'data/b2_images.json',
        'USERS': 'data/users.json'
    }
}

# Initialize Backblaze B2 client
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
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# ==================== CONFIGURATION CONSTANTS ====================
CONFIG = {
    'APP_NAME': 'Karanja Shoe Store',
    'MAX_IMAGE_SIZE': 20 * 1024 * 1024,
    'LOW_STOCK_THRESHOLD': 3,
    'OLD_STOCK_DAYS': 30,
    'CURRENCY': 'KES',
    'TITHE_PERCENTAGE': 10,
    'SAVINGS_PERCENTAGE': 20,
    'RESTOCK_PERCENTAGE': 30,
    'DEDUCTIONS_PERCENTAGE': 15,
    'PERSONAL_INCOME_PERCENTAGE': 25,
    'BUSINESS_HEALTH_GOAL': 10000,
    'DAILY_STATEMENT_TIME': 21,
    'SIZE_RANGE': {'MIN': 1, 'MAX': 50},
    'B2_CONFIG': B2_CONFIG
}

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

# ==================== B2 DATA STORAGE MANAGER ====================
class B2DataStore:
    """All data stored in Backblaze B2 - Complete cloud storage"""
    
    def __init__(self, b2_client, bucket_name):
        self.b2_client = b2_client
        self.bucket_name = bucket_name
        self.cache = {}  # In-memory cache for performance
        self.load_all_data()
    
    def _read_json_from_b2(self, b2_key):
        """Read JSON data from B2 bucket"""
        try:
            response = self.b2_client.get_object(
                Bucket=self.bucket_name,
                Key=b2_key
            )
            content = response['Body'].read().decode('utf-8')
            return json.loads(content) if content.strip() else {}
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                # File doesn't exist yet - return empty dict
                return {}
            logger.error(f"Error reading {b2_key} from B2: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error reading {b2_key} from B2: {e}")
            return {}
    
    def _write_json_to_b2(self, b2_key, data):
        """Write JSON data to B2 bucket"""
        try:
            json_str = json.dumps(data, cls=CustomJSONEncoder, indent=2)
            self.b2_client.put_object(
                Bucket=self.bucket_name,
                Key=b2_key,
                Body=json_str.encode('utf-8'),
                ContentType='application/json',
                CacheControl='no-cache'
            )
            logger.info(f"Successfully wrote {b2_key} to B2")
            return True
        except Exception as e:
            logger.error(f"Error writing {b2_key} to B2: {e}")
            return False
    
    def load_all_data(self):
        """Load all data from B2 into cache"""
        self.cache['products'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['PRODUCTS'])
        self.cache['sales'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SALES'])
        self.cache['notifications'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['NOTIFICATIONS'])
        self.cache['settings'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SETTINGS'])
        self.cache['monthly_category_sales'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['MONTHLY_CATEGORY_SALES'])
        self.cache['daily_statements'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['DAILY_STATEMENTS'])
        self.cache['budget_plans'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['BUDGET_PLANS'])
        self.cache['sale_statements'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['SALE_STATEMENTS'])
        self.cache['b2_images'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'])
        self.cache['users'] = self._read_json_from_b2(B2_CONFIG['DATA_PATHS']['USERS'])
        
        # Initialize default values if empty
        if not self.cache['products']:
            self.cache['products'] = []
        if not self.cache['sales']:
            self.cache['sales'] = []
        if not self.cache['notifications']:
            self.cache['notifications'] = []
        if not self.cache['settings']:
            self.cache['settings'] = {
                'currency': 'KES',
                'low_stock_threshold': 3,
                'old_stock_days': 30,
                'theme': 'light',
                'b2_bucket': B2_CONFIG['BUCKET_ID'],
                'b2_endpoint': B2_CONFIG['ENDPOINT'],
                'b2_created': B2_CONFIG['CREATED_DATE']
            }
        if not self.cache['monthly_category_sales']:
            self.cache['monthly_category_sales'] = {}
        if not self.cache['daily_statements']:
            self.cache['daily_statements'] = []
        if not self.cache['budget_plans']:
            self.cache['budget_plans'] = []
        if not self.cache['sale_statements']:
            self.cache['sale_statements'] = []
        if not self.cache['b2_images']:
            self.cache['b2_images'] = []
        if not self.cache['users']:
            self.cache['users'] = []
    
    # ========== Products ==========
    @property
    def products(self):
        return self.cache.get('products', [])
    
    def save_products(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['PRODUCTS'], self.products)
    
    # ========== Sales ==========
    @property
    def sales(self):
        return self.cache.get('sales', [])
    
    def save_sales(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SALES'], self.sales)
    
    # ========== Notifications ==========
    @property
    def notifications(self):
        return self.cache.get('notifications', [])
    
    def save_notifications(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['NOTIFICATIONS'], self.notifications)
    
    # ========== Settings ==========
    @property
    def settings(self):
        return self.cache.get('settings', {})
    
    def save_settings(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SETTINGS'], self.settings)
    
    # ========== Monthly Category Sales ==========
    @property
    def monthly_category_sales(self):
        return self.cache.get('monthly_category_sales', {})
    
    def save_monthly_category_sales(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['MONTHLY_CATEGORY_SALES'], self.monthly_category_sales)
    
    # ========== Daily Statements ==========
    @property
    def daily_statements(self):
        return self.cache.get('daily_statements', [])
    
    def save_daily_statements(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['DAILY_STATEMENTS'], self.daily_statements)
    
    # ========== Budget Plans ==========
    @property
    def budget_plans(self):
        return self.cache.get('budget_plans', [])
    
    def save_budget_plans(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['BUDGET_PLANS'], self.budget_plans)
    
    # ========== Sale Statements ==========
    @property
    def sale_statements(self):
        return self.cache.get('sale_statements', [])
    
    def save_sale_statements(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['SALE_STATEMENTS'], self.sale_statements)
    
    # ========== B2 Images ==========
    @property
    def b2_images(self):
        return self.cache.get('b2_images', [])
    
    def save_b2_images(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['B2_IMAGES'], self.b2_images)
    
    # ========== Users ==========
    @property
    def users(self):
        return self.cache.get('users', [])
    
    def save_users(self):
        return self._write_json_to_b2(B2_CONFIG['DATA_PATHS']['USERS'], self.users)
    
    # ========== Save All ==========
    def save_all(self):
        """Save all data to B2"""
        self.save_products()
        self.save_sales()
        self.save_notifications()
        self.save_settings()
        self.save_monthly_category_sales()
        self.save_daily_statements()
        self.save_budget_plans()
        self.save_sale_statements()
        self.save_b2_images()
        self.save_users()

# Initialize B2 Data Store
b2_store = B2DataStore(b2_client, B2_CONFIG['BUCKET_NAME'])

# Initialize default admin if no users exist
if not b2_store.users:
    admin_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
    b2_store.cache['users'] = [{
        'id': 1,
        'email': 'admin@karanjashoes.com',
        'password': admin_password,
        'name': 'Admin Karanja',
        'role': 'admin',
        'created_at': datetime.now().isoformat()
    }]
    b2_store.save_users()
    logger.info("Created default admin user in B2")

# ==================== BACKBLAZE B2 HELPER FUNCTIONS ====================
def generate_signed_url(s3_key, expiration=604800):
    """
    Generate a pre-signed URL for private B2 bucket access
    Default expiration: 7 days (604800 seconds)
    """
    try:
        if not s3_key:
            logger.warning("No s3_key provided for signed URL generation")
            return None
        
        url = b2_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': B2_CONFIG['BUCKET_NAME'],
                'Key': s3_key
            },
            ExpiresIn=expiration
        )
        logger.info(f"Generated signed URL for {s3_key} (expires in {expiration}s)")
        return url
    except ClientError as e:
        logger.error(f"B2 ClientError generating signed URL: {e}")
        return None
    except Exception as e:
        logger.error(f"Error generating signed URL: {e}")
        return None

def extract_s3_key_from_url(url):
    """Extract S3 key from B2 URL (CDN or signed URL)"""
    if not url:
        return None
    
    try:
        # Handle CDN URL format
        if B2_CONFIG['CDN_URL'] in url:
            return url.replace(f"{B2_CONFIG['CDN_URL']}/", '')
        
        # Handle signed URL format - extract path before query string
        if 's3.eu-central-003' in url or 'backblazeb2.com' in url:
            import re
            match = re.search(r'products/[^?]+', url)
            if match:
                return match.group(0)
        
        # Handle direct key
        if url.startswith('products/'):
            return url
    except Exception as e:
        logger.error(f"Error extracting S3 key from URL: {e}")
    
    return None

# ==================== BACKBLAZE B2 ROUTES ====================
@app.route('/api/b2/upload', methods=['POST'])
@jwt_required()
def upload_to_b2():
    """Upload image to Backblaze B2 Private Bucket with signed URL"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        unique_filename = f"{timestamp}_{safe_filename}"
        s3_key = f"products/{unique_filename}"
        
        # Detect mime type
        content_type = file.content_type
        if not content_type:
            content_type = mimetypes.guess_type(file.filename)[0] or 'image/jpeg'
        
        logger.info(f"Uploading {s3_key} to B2 bucket {B2_CONFIG['BUCKET_NAME']}")
        
        # Upload to B2
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
        
        # Generate signed URL (7 days expiration)
        signed_url = generate_signed_url(s3_key, expiration=604800)
        
        # CDN URL (for reference only - won't work with private bucket)
        cdn_url = f"{B2_CONFIG['CDN_URL']}/{s3_key}"
        
        # Store record in B2
        image_record = {
            'id': str(uuid.uuid4()),
            'cdn_url': cdn_url,
            'signed_url': signed_url,
            's3_key': s3_key,
            'fileName': unique_filename,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'size': request.content_length or 0,
            'type': content_type,
            'uploadedAt': datetime.now().isoformat(),
            'expiresAt': (datetime.now() + timedelta(days=7)).isoformat(),
            'uploadedBy': get_jwt_identity()
        }
        
        b2_store.b2_images.append(image_record)
        b2_store.save_b2_images()
        
        logger.info(f"Successfully uploaded {s3_key} to B2")
        
        return jsonify({
            'success': True,
            'url': signed_url,  # This WILL work (private bucket signed URL)
            'signed_url': signed_url,
            'cdn_url': cdn_url,
            'fileName': unique_filename,
            's3_key': s3_key,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'expires_in': '7 days',
            'expires_at': (datetime.now() + timedelta(days=7)).isoformat(),
            'current_files': B2_CONFIG['CURRENT_FILES'],
            'current_size': B2_CONFIG['CURRENT_SIZE'],
            'bucket_type': B2_CONFIG['TYPE'],
            'created': B2_CONFIG['CREATED_DATE']
        }), 200
        
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        logger.error(f"B2 upload failed: {error_code} - {error_message}")
        return jsonify({
            'error': f'B2 upload failed: {error_code} - {error_message}',
            'details': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error in upload: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== LOCAL FILE UPLOAD ROUTE (FALLBACK) ====================
@app.route('/api/upload/local', methods=['POST'])
@jwt_required()
def upload_local():
    """Upload image locally (fallback if B2 fails)"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        filename = f"{timestamp}_{safe_filename}"
        
        # Save to static/uploads folder
        upload_path = os.path.join('static', 'uploads', filename)
        file.save(upload_path)
        
        # Generate URL
        file_url = f"/static/uploads/{filename}"
        
        logger.info(f"Successfully uploaded locally: {filename}")
        
        return jsonify({
            'success': True,
            'url': file_url,
            'fileName': filename,
            'local': True
        }), 200
        
    except Exception as e:
        logger.error(f"Error in local upload: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with fresh signed URLs"""
    try:
        search = request.args.get('search', '').lower()
        category = request.args.get('category')
        in_stock = request.args.get('in_stock', '').lower() == 'true'
        
        products = b2_store.products
        
        # Apply filters
        if search:
            products = [p for p in products if 
                       search in p.get('name', '').lower() or
                       search in p.get('sku', '').lower() or
                       search in p.get('category', '').lower() or
                       search in p.get('color', '').lower()]
        
        if category:
            products = [p for p in products if p.get('category') == category]
        
        if in_stock:
            products = [p for p in products if p.get('totalStock', 0) > 0]
        
        # Sort by date added (newest first)
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Generate fresh signed URLs for all products
        products_copy = []
        for product in products:
            product_copy = product.copy()
            
            # Handle B2 images
            if product.get('s3_key'):
                fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
                if fresh_url:
                    product_copy['image'] = fresh_url
                    product_copy['image_expires'] = (datetime.now() + timedelta(days=1)).isoformat()
            
            # Handle local images
            elif product.get('local_image'):
                product_copy['image'] = product['local_image']
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product - SUPPORTS BOTH JSON AND FORM DATA"""
    try:
        # Check if this is form-data (from HTML form) or JSON (from API)
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Handle form data from HTML upload
            name = request.form.get('name')
            price = request.form.get('price')
            description = request.form.get('description', '')
            image_url = request.form.get('image_url')
            sizes_json = request.form.get('sizes', '{}')
            
            # Parse sizes
            try:
                sizes = json.loads(sizes_json)
            except:
                sizes = {}
            
            # Get category, color etc
            category = request.form.get('category', 'Uncategorized')
            color = request.form.get('color', '')
            sku = request.form.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}")
            
            # Calculate total stock
            total_stock = 0
            for size, stock in sizes.items():
                try:
                    total_stock += int(stock) if stock and int(stock) > 0 else 0
                except:
                    pass
            
        else:
            # Handle JSON data from API
            data = request.get_json()
            name = data.get('name')
            price = data.get('price')
            description = data.get('description', '')
            image_url = data.get('image')
            sizes = data.get('sizes', {})
            category = data.get('category', 'Uncategorized')
            color = data.get('color', '')
            sku = data.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}")
            
            # Calculate total stock
            total_stock = 0
            for size, stock in sizes.items():
                try:
                    total_stock += int(stock) if stock and int(stock) > 0 else 0
                except:
                    pass
        
        # Validate required fields
        if not name:
            return jsonify({'error': 'Product name is required'}), 400
        
        if not price:
            return jsonify({'error': 'Price is required'}), 400
        
        # Extract S3 key from image URL if it's from B2
        s3_key = None
        if image_url and 'backblazeb2.com' in image_url:
            s3_key = extract_s3_key_from_url(image_url)
        
        # Generate signed URL if we have s3_key
        signed_url = None
        if s3_key:
            signed_url = generate_signed_url(s3_key, expiration=604800)  # 7 days
        
        # Create product object
        product = {
            'id': int(datetime.now().timestamp() * 1000),
            'name': name.strip(),
            'price': float(price),
            'description': description.strip(),
            'sku': sku,
            'category': category,
            'color': color,
            'sizes': sizes,
            'totalStock': total_stock,
            'dateAdded': datetime.now().isoformat(),
            'lastUpdated': datetime.now().isoformat(),
            'createdBy': get_jwt_identity()
        }
        
        # Handle image - prioritize B2, fallback to local
        if signed_url:
            product['image'] = signed_url
            product['s3_key'] = s3_key
            product['cdn_url'] = f"{B2_CONFIG['CDN_URL']}/{s3_key}" if s3_key else None
            product['image_source'] = 'b2'
        elif image_url and not image_url.startswith('http'):
            # Local image path
            product['image'] = image_url
            product['local_image'] = image_url
            product['image_source'] = 'local'
        elif image_url and image_url.startswith('http'):
            # External URL
            product['image'] = image_url
            product['image_source'] = 'external'
        else:
            # Default placeholder
            product['image'] = '/static/placeholder.png'
            product['image_source'] = 'placeholder'
        
        # Add to store
        b2_store.products.append(product)
        b2_store.save_products()
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'New product added: {product["name"]}',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        b2_store.notifications.insert(0, notification)
        b2_store.save_notifications()
        
        logger.info(f"Product created: {product['name']} (ID: {product['id']})")
        
        return jsonify({
            'success': True,
            'message': 'Product uploaded successfully!',
            'product': product
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== STATIC FILE SERVING ====================
@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    return send_from_directory('static', filename)

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    """Serve uploaded files"""
    return send_from_directory('static/uploads', filename)

# ==================== PUBLIC PRODUCT ROUTES (NO AUTH) ====================
@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint to get products - NO LOGIN REQUIRED"""
    try:
        products = b2_store.products
        
        # Sort by date added (newest first)
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Generate fresh signed URLs for all products
        products_copy = []
        for product in products:
            product_copy = product.copy()
            
            # Remove sensitive data
            if 'buyPrice' in product_copy:
                del product_copy['buyPrice']
            if 'createdBy' in product_copy:
                del product_copy['createdBy']
            
            # Handle B2 images
            if product.get('s3_key'):
                fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
                if fresh_url:
                    product_copy['image'] = fresh_url
            
            # Handle local images
            elif product.get('local_image'):
                product_copy['image'] = product['local_image']
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

# ==================== HTML PAGE ROUTES ====================
@app.route('/')
def index():
    """Serve the main index.html page"""
    try:
        # Try to serve index.html from current directory
        if os.path.exists('index.html'):
            with open('index.html', 'r') as f:
                content = f.read()
                return render_template_string(content)
        else:
            # Create a simple HTML page if index.html doesn't exist
            return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Karanja Shoe Store</title>
                <style>
                    body {
                        font-family: Arial, sans-serif;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        min-height: 100vh;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        margin: 0;
                        padding: 20px;
                    }
                    .container {
                        background: white;
                        padding: 40px;
                        border-radius: 10px;
                        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
                        max-width: 800px;
                        text-align: center;
                    }
                    h1 { color: #333; }
                    p { color: #666; line-height: 1.6; }
                    .badge {
                        background: #667eea;
                        color: white;
                        padding: 5px 10px;
                        border-radius: 5px;
                        display: inline-block;
                        margin: 10px 0;
                    }
                    .success { color: #28a745; }
                    .info { background: #e3f2fd; padding: 15px; border-radius: 5px; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>👟 Karanja Shoe Store</h1>
                    <div class="badge">Backblaze B2 Cloud Storage</div>
                    <div class="badge" style="background: #764ba2;">Bucket: {{ bucket_name }}</div>
                    <p class="success">✓ Backend is running successfully!</p>
                    <div class="info">
                        <h3>📊 System Status</h3>
                        <p>📦 Products: {{ products_count }}</p>
                        <p>🖼️ B2 Images: {{ images_count }}</p>
                        <p>📁 Bucket Created: {{ bucket_created }}</p>
                        <p>💾 Data Storage: 100% Backblaze B2</p>
                    </div>
                    <p>Please ensure <strong>index.html</strong> is in the same directory as app.py</p>
                </div>
            </body>
            </html>
            ''', 
            bucket_name=B2_CONFIG['BUCKET_NAME'],
            products_count=len(b2_store.products),
            images_count=len(b2_store.b2_images),
            bucket_created=B2_CONFIG['CREATED_DATE'])
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({
            'status': 'running',
            'message': 'Karanja Shoe Store API is running',
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'b2_created': B2_CONFIG['CREATED_DATE'],
            'products': len(b2_store.products),
            'images': len(b2_store.b2_images),
            'endpoints': {
                'public_products': '/api/public/products',
                'upload': '/api/b2/upload',
                'login': '/api/auth/login'
            }
        }), 200

@app.route('/products')
def products_page():
    """Serve products page"""
    return index()

@app.route('/upload')
def upload_page():
    """Serve upload page"""
    return index()

@app.route('/admin')
def admin_page():
    """Serve admin page"""
    return index()

# ==================== AUTHENTICATION ROUTES ====================
@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user and return JWT token"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({'error': 'Email and password required'}), 400
        
        user = next((u for u in b2_store.users if u['email'] == email), None)
        
        if user and bcrypt.check_password_hash(user['password'], password):
            access_token = create_access_token(
                identity=str(user['id']),
                additional_claims={
                    'email': user['email'],
                    'name': user['name'],
                    'role': user['role']
                }
            )
            
            logger.info(f"User logged in: {email}")
            
            return jsonify({
                'success': True,
                'token': access_token,
                'user': {
                    'id': user['id'],
                    'email': user['email'],
                    'name': user['name'],
                    'role': user['role']
                }
            }), 200
        
        logger.warning(f"Failed login attempt for: {email}")
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user"""
    try:
        current_user_id = get_jwt_identity()
        user = next((u for u in b2_store.users if str(u['id']) == current_user_id), None)
        
        if user:
            return jsonify({
                'id': user['id'],
                'email': user['email'],
                'name': user['name'],
                'role': user['role']
            }), 200
        
        return jsonify({'error': 'User not found'}), 404
        
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== B2 INFO ROUTES ====================
@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get Backblaze B2 bucket information"""
    try:
        return jsonify({
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'region': B2_CONFIG['REGION'],
            'created': B2_CONFIG['CREATED_DATE'],
            'cdn_url': B2_CONFIG['CDN_URL'],
            'type': B2_CONFIG['TYPE'],
            'current_files': B2_CONFIG['CURRENT_FILES'],
            'current_size': B2_CONFIG['CURRENT_SIZE'],
            'stored_images': len(b2_store.b2_images),
            'connected': True,
            'data_files': list(B2_CONFIG['DATA_PATHS'].values())
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'created': B2_CONFIG['CREATED_DATE'],
            'type': B2_CONFIG['TYPE'],
            'connected': False,
            'error': str(e)
        }), 200

@app.route('/api/b2/images', methods=['GET'])
@jwt_required()
def get_b2_images():
    """Get all B2 images with fresh signed URLs"""
    try:
        images = []
        for img in b2_store.b2_images[-50:]:  # Last 50 images
            img_copy = img.copy()
            # Generate fresh signed URL
            fresh_url = generate_signed_url(img['s3_key'], expiration=86400)
            if fresh_url:
                img_copy['signed_url'] = fresh_url
                img_copy['url'] = fresh_url
            images.append(img_copy)
        
        return jsonify(images), 200
    except Exception as e:
        logger.error(f"Error getting B2 images: {e}")
        return jsonify([]), 200

# ==================== DASHBOARD STATS ROUTES ====================
@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        # Get all products and sales
        products = b2_store.products
        sales = b2_store.sales
        
        # Calculate stats
        total_products = len(products)
        total_stock = sum([p.get('totalStock', 0) for p in products])
        
        # Calculate total sales
        total_revenue = sum([s.get('totalAmount', 0) for s in sales])
        total_profit = sum([s.get('totalProfit', 0) for s in sales])
        
        # Get today's sales
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
    """Get all notifications"""
    try:
        unread_only = request.args.get('unread', '').lower() == 'true'
        
        notifications = b2_store.notifications
        
        if unread_only:
            notifications = [n for n in notifications if not n.get('read', False)]
        
        return jsonify(notifications[:50]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_unread_notification_count():
    """Get unread notification count"""
    try:
        unread_count = len([n for n in b2_store.notifications if not n.get('read', False)])
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        notification = next((n for n in b2_store.notifications if n['id'] == notification_id), None)
        
        if notification:
            notification['read'] = True
            b2_store.save_notifications()
            return jsonify({'success': True}), 200
        
        return jsonify({'error': 'Notification not found'}), 404
    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications/read-all', methods=['PUT'])
@jwt_required()
def mark_all_notifications_read():
    """Mark all notifications as read"""
    try:
        for notification in b2_store.notifications:
            notification['read'] = True
        
        b2_store.save_notifications()
        
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error marking all notifications read: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== SETTINGS ROUTES ====================
@app.route('/api/settings', methods=['GET'])
@jwt_required()
def get_settings():
    """Get application settings"""
    try:
        return jsonify(b2_store.settings), 200
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({}), 200

@app.route('/api/settings', methods=['PUT'])
@jwt_required()
def update_settings():
    """Update application settings"""
    try:
        data = request.get_json()
        b2_store.settings.update(data)
        b2_store.save_settings()
        return jsonify(b2_store.settings), 200
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test B2 connection
        b2_status = 'connected'
        try:
            b2_client.list_buckets()
        except:
            b2_status = 'disconnected'
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'app': 'Karanja Shoe Store',
            'created': 'February 9, 2026',
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'b2_bucket_id': B2_CONFIG['BUCKET_ID'],
            'b2_created': B2_CONFIG['CREATED_DATE'],
            'b2_type': B2_CONFIG['TYPE'],
            'b2_files': B2_CONFIG['CURRENT_FILES'],
            'b2_size': B2_CONFIG['CURRENT_SIZE'],
            'b2_status': b2_status,
            'products': len(b2_store.products),
            'images': len(b2_store.b2_images),
            'data_storage': 'Backblaze B2 (100% cloud storage)',
            'local_storage': 'Static files served locally'
        }), 200
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return jsonify({
            'status': 'degraded',
            'timestamp': datetime.now().isoformat(),
            'app': 'Karanja Shoe Store',
            'error': str(e)
        }), 200

# ==================== INITIALIZE SAMPLE DATA ====================
def init_sample_data():
    """Initialize sample data if no products exist"""
    try:
        if len(b2_store.products) == 0:
            # Create placeholder image if it doesn't exist
            placeholder_path = os.path.join('static', 'placeholder.png')
            if not os.path.exists(placeholder_path):
                os.makedirs('static', exist_ok=True)
                # Create a simple colored placeholder
                from PIL import Image
                try:
                    img = Image.new('RGB', (300, 300), color=(102, 126, 234))
                    img.save(placeholder_path)
                except:
                    logger.warning("Could not create placeholder image (PIL not installed)")
            
            # Add welcome notification
            notification = {
                'id': int(datetime.now().timestamp() * 1000),
                'message': f'Welcome to Karanja Shoe Store! ALL data stored in Backblaze B2 bucket: {B2_CONFIG["BUCKET_NAME"]} (Created: {B2_CONFIG["CREATED_DATE"]})',
                'type': 'info',
                'timestamp': datetime.now().isoformat(),
                'read': False
            }
            b2_store.notifications.insert(0, notification)
            b2_store.save_notifications()
            logger.info("Sample data initialized in B2")
    except Exception as e:
        logger.error(f"Error initializing data: {e}")

# Initialize sample data
init_sample_data()

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return index()

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
    app.run(host='0.0.0.0', port=port, debug=True)
