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
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['STATIC_FOLDER'] = 'static'

# Create static folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

# ==================== BACKBLAZE B2 CONFIGURATION ====================
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
    """Generate a pre-signed URL for private B2 bucket access"""
    try:
        if not s3_key:
            return None
        
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

# ==================== BACKBLAZE B2 UPLOAD ROUTE ====================
@app.route('/api/b2/upload', methods=['POST'])
@jwt_required()
def upload_to_b2():
    """Upload image to Backblaze B2 Private Bucket"""
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
        
        # Generate signed URL
        signed_url = generate_signed_url(s3_key, expiration=604800)
        
        # Store record in B2
        image_record = {
            'id': str(uuid.uuid4()),
            'signed_url': signed_url,
            's3_key': s3_key,
            'fileName': unique_filename,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'uploadedAt': datetime.now().isoformat()
        }
        
        b2_store.b2_images.append(image_record)
        b2_store.save_b2_images()
        
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

# ==================== LOCAL FILE UPLOAD ROUTE (FALLBACK) ====================
@app.route('/api/upload/local', methods=['POST'])
@jwt_required()
def upload_local():
    """Upload image locally (fallback)"""
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
        products = b2_store.products
        
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
            
            # Handle local images
            elif product.get('local_image'):
                product_copy['image'] = product['local_image']
            
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

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

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product - SUPPORTS FORM DATA (with image)"""
    try:
        # Get form data
        name = request.form.get('name')
        price = request.form.get('price')
        description = request.form.get('description', '')
        category = request.form.get('category', 'Uncategorized')
        color = request.form.get('color', '')
        sku = request.form.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}")
        
        # Get sizes JSON
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
        except:
            sizes = {}
        
        # Get buy price and sell price range
        buy_price = request.form.get('buyPrice')
        min_sell_price = request.form.get('minSellPrice')
        max_sell_price = request.form.get('maxSellPrice')
        
        # Image URL from upload
        image_url = request.form.get('image_url')
        
        # Validate required fields
        if not name:
            return jsonify({'error': 'Product name is required'}), 400
        
        if not price and not max_sell_price:
            return jsonify({'error': 'Price is required'}), 400
        
        # Use price as max_sell_price if not provided
        if not max_sell_price and price:
            max_sell_price = price
        if not min_sell_price and price:
            min_sell_price = price
        
        # Calculate total stock
        total_stock = 0
        for size, stock in sizes.items():
            try:
                total_stock += int(stock) if stock and int(stock) > 0 else 0
            except:
                pass
        
        # Extract S3 key from image URL if it's from B2
        s3_key = None
        if image_url and 'backblazeb2.com' in image_url:
            s3_key = extract_s3_key_from_url(image_url)
        
        # Generate signed URL if we have s3_key
        signed_url = None
        if s3_key:
            signed_url = generate_signed_url(s3_key, expiration=604800)
        
        # Create product object
        product = {
            'id': int(datetime.now().timestamp() * 1000),
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
            'createdBy': get_jwt_identity()
        }
        
        # Handle image
        if signed_url:
            product['image'] = signed_url
            product['s3_key'] = s3_key
            product['image_source'] = 'b2'
        elif image_url and image_url.startswith('/static/'):
            product['image'] = image_url
            product['local_image'] = image_url
            product['image_source'] = 'local'
        elif image_url and image_url.startswith('http'):
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
        
        return jsonify({
            'success': True,
            'message': 'Product uploaded successfully!',
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
    try:
        product = next((p for p in b2_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Get form data
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
        
        # Update fields if provided
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
        
        # Update sizes
        if sizes_json:
            try:
                sizes = json.loads(sizes_json)
                product['sizes'] = sizes
                
                # Recalculate total stock
                total_stock = 0
                for size, stock in sizes.items():
                    try:
                        total_stock += int(stock) if stock and int(stock) > 0 else 0
                    except:
                        pass
                product['totalStock'] = total_stock
            except:
                pass
        
        # Update image
        if image_url:
            s3_key = extract_s3_key_from_url(image_url)
            if s3_key:
                product['s3_key'] = s3_key
                product['image'] = generate_signed_url(s3_key, expiration=604800)
                product['image_source'] = 'b2'
            elif image_url.startswith('/static/'):
                product['local_image'] = image_url
                product['image'] = image_url
                product['image_source'] = 'local'
            else:
                product['image'] = image_url
                product['image_source'] = 'external'
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        b2_store.save_products()
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully!',
            'product': product
        }), 200
        
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    try:
        product = next((p for p in b2_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        b2_store.products = [p for p in b2_store.products if p['id'] != product_id]
        b2_store.save_products()
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Product deleted: {product["name"]}',
            'type': 'warning',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        b2_store.notifications.insert(0, notification)
        b2_store.save_notifications()
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
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

# ==================== DASHBOARD STATS ====================
@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        products = b2_store.products
        sales = b2_store.sales
        
        total_products = len(products)
        total_stock = sum([p.get('totalStock', 0) for p in products])
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

# ==================== SALES ROUTES ====================
@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Record new sale"""
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
        
        product = next((p for p in b2_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        size_key = str(size)
        if size_key not in product['sizes'] or product['sizes'][size_key] < quantity:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Update stock
        product['sizes'][size_key] -= quantity
        if product['sizes'][size_key] < 0:
            product['sizes'][size_key] = 0
        
        # Recalculate total stock
        total_stock = 0
        for stock in product['sizes'].values():
            total_stock += stock if stock > 0 else 0
        product['totalStock'] = total_stock
        product['lastUpdated'] = datetime.now().isoformat()
        
        b2_store.save_products()
        
        # Calculate amounts
        total_amount = unit_price * quantity
        total_cost = product['buyPrice'] * quantity
        total_profit = total_amount - total_cost
        
        # Create sale record
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
        
        b2_store.sales.append(sale)
        b2_store.save_sales()
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Sale recorded: {product["name"]} ({quantity} × Size {size})',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        b2_store.notifications.insert(0, notification)
        b2_store.save_notifications()
        
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
    try:
        sales = b2_store.sales
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
    try:
        notifications = b2_store.notifications[:50]
        return jsonify(notifications), 200
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
            'connected': True
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'app': 'Karanja Shoe Store',
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'b2_created': B2_CONFIG['CREATED_DATE'],
            'products': len(b2_store.products),
            'sales': len(b2_store.sales),
            'images': len(b2_store.b2_images)
        }), 200
    except Exception as e:
        return jsonify({'status': 'degraded', 'error': str(e)}), 200

# ==================== STATIC PAGE ROUTES ====================
@app.route('/')
def index():
    """Serve index.html"""
    try:
        if os.path.exists('index.html'):
            with open('index.html', 'r', encoding='utf-8') as f:
                return render_template_string(f.read())
        else:
            return jsonify({
                'message': 'Karanja Shoe Store API is running',
                'b2_bucket': B2_CONFIG['BUCKET_NAME'],
                'products': len(b2_store.products),
                'status': 'online'
            }), 200
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Could not load index.html'}), 500

# Catch-all route for SPA
@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API routes"""
    if path.startswith('api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return index()

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

# ==================== INITIALIZE SAMPLE DATA ====================
def init_sample_data():
    """Initialize sample data if no products exist"""
    try:
        if len(b2_store.products) == 0:
            # Create placeholder image
            placeholder_path = os.path.join('static', 'placeholder.png')
            if not os.path.exists(placeholder_path):
                os.makedirs('static', exist_ok=True)
                try:
                    from PIL import Image, ImageDraw
                    img = Image.new('RGB', (300, 300), color=(102, 126, 234))
                    draw = ImageDraw.Draw(img)
                    draw.text((150, 150), "No Image", fill="white", anchor="mm")
                    img.save(placeholder_path)
                    logger.info("Created placeholder image")
                except ImportError:
                    logger.warning("PIL not installed, skipping placeholder creation")
            
            # Add welcome notification
            notification = {
                'id': int(datetime.now().timestamp() * 1000),
                'message': f'Welcome to Karanja Shoe Store! Data stored in Backblaze B2 bucket: {B2_CONFIG["BUCKET_NAME"]}',
                'type': 'info',
                'timestamp': datetime.now().isoformat(),
                'read': False
            }
            b2_store.notifications.insert(0, notification)
            b2_store.save_notifications()
            logger.info("Sample data initialized")
    except Exception as e:
        logger.error(f"Error initializing data: {e}")

# Initialize sample data
init_sample_data()

# ==================== RUN APPLICATION ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
