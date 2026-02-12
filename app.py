from flask import Flask, request, jsonify, send_file, render_template_string
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
import requests
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
    'CURRENT_SIZE': '24.3 MB'
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

# ==================== DATA STORAGE ====================
class DataStore:
    """In-memory data store with file persistence"""
    
    def __init__(self):
        self.products = []
        self.sales = []
        self.notifications = []
        self.settings = {
            'currency': 'KES',
            'low_stock_threshold': 3,
            'old_stock_days': 30,
            'theme': 'light',
            'b2_bucket': B2_CONFIG['BUCKET_ID'],
            'b2_endpoint': B2_CONFIG['ENDPOINT'],
            'b2_created': B2_CONFIG['CREATED_DATE']
        }
        self.monthly_category_sales = {}
        self.daily_statements = []
        self.budget_plans = []
        self.sale_statements = []
        self.b2_images = []
        self.users = []
        self.load_data()
    
    def load_data(self):
        """Load data from JSON files"""
        try:
            if os.path.exists('data.json'):
                with open('data.json', 'r') as f:
                    data = json.load(f)
                    self.products = data.get('products', [])
                    self.sales = data.get('sales', [])
                    self.notifications = data.get('notifications', [])
                    self.settings.update(data.get('settings', {}))
                    self.monthly_category_sales = data.get('monthly_category_sales', {})
                    self.daily_statements = data.get('daily_statements', [])
                    self.budget_plans = data.get('budget_plans', [])
                    self.sale_statements = data.get('sale_statements', [])
                    self.b2_images = data.get('b2_images', [])
                    self.users = data.get('users', [])
                    logger.info(f"Loaded {len(self.products)} products, {len(self.sales)} sales")
        except Exception as e:
            logger.error(f"Error loading data: {e}")
        
        # Initialize default admin if no users exist
        if not self.users:
            admin_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
            self.users.append({
                'id': 1,
                'email': 'admin@karanjashoes.com',
                'password': admin_password,
                'name': 'Admin Karanja',
                'role': 'admin',
                'created_at': datetime.now().isoformat()
            })
            self.save_data()
            logger.info("Created default admin user")
    
    def save_data(self):
        """Save data to JSON file"""
        try:
            data = {
                'products': self.products,
                'sales': self.sales,
                'notifications': self.notifications,
                'settings': self.settings,
                'monthly_category_sales': self.monthly_category_sales,
                'daily_statements': self.daily_statements,
                'budget_plans': self.budget_plans,
                'sale_statements': self.sale_statements,
                'b2_images': self.b2_images,
                'users': self.users
            }
            with open('data.json', 'w') as f:
                json.dump(data, f, cls=CustomJSONEncoder, indent=2)
            logger.info("Data saved successfully")
        except Exception as e:
            logger.error(f"Error saving data: {e}")

data_store = DataStore()

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
        if 's3.eu-central-003' in url:
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
        
        # Validate file size
        if request.content_length and request.content_length > CONFIG['MAX_IMAGE_SIZE']:
            return jsonify({'error': 'Image size exceeds 20MB'}), 400
        
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
        
        # Store record
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
        
        data_store.b2_images.append(image_record)
        data_store.save_data()
        
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

@app.route('/api/b2/signed-url', methods=['POST'])
@jwt_required()
def get_signed_url_endpoint():
    """Generate fresh signed URL for existing image"""
    try:
        data = request.get_json()
        s3_key = data.get('s3_key')
        expiration = data.get('expiration', 86400)  # Default 24 hours
        
        if not s3_key:
            return jsonify({'error': 's3_key is required'}), 400
        
        signed_url = generate_signed_url(s3_key, expiration)
        
        if signed_url:
            return jsonify({
                'success': True,
                'url': signed_url,
                's3_key': s3_key,
                'expires_in': expiration,
                'expires_at': (datetime.now() + timedelta(seconds=expiration)).isoformat()
            }), 200
        else:
            return jsonify({'error': 'Failed to generate signed URL'}), 500
            
    except Exception as e:
        logger.error(f"Error generating signed URL: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get Backblaze B2 bucket information"""
    try:
        # Get real-time bucket stats
        response = b2_client.list_objects_v2(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            MaxKeys=1
        )
        
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
            'stored_images': len(data_store.b2_images),
            'connected': True
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'created': B2_CONFIG['CREATED_DATE'],
            'type': B2_CONFIG['TYPE'],
            'current_files': B2_CONFIG['CURRENT_FILES'],
            'current_size': B2_CONFIG['CURRENT_SIZE'],
            'connected': False,
            'error': str(e)
        }), 200

@app.route('/api/b2/diagnose', methods=['GET'])
@jwt_required()
def diagnose_b2():
    """Complete B2 connection diagnosis"""
    results = {
        'bucket': B2_CONFIG['BUCKET_NAME'],
        'bucket_id': B2_CONFIG['BUCKET_ID'],
        'endpoint': B2_CONFIG['ENDPOINT'],
        'cdn_url': B2_CONFIG['CDN_URL'],
        'type': B2_CONFIG['TYPE'],
        'created': B2_CONFIG['CREATED_DATE'],
        'tests': {},
        'credentials': {
            'access_key_id': B2_CONFIG['ACCESS_KEY_ID'][:4] + '...' + B2_CONFIG['ACCESS_KEY_ID'][-4:],
            'bucket_name': B2_CONFIG['BUCKET_NAME']
        }
    }
    
    # Test 1: List buckets (check credentials)
    try:
        response = b2_client.list_buckets()
        buckets = [b['Name'] for b in response['Buckets']]
        results['tests']['list_buckets'] = {
            'success': True,
            'buckets': buckets,
            'message': f"Successfully authenticated. Found {len(buckets)} buckets."
        }
    except Exception as e:
        results['tests']['list_buckets'] = {
            'success': False,
            'error': str(e),
            'message': 'Failed to list buckets. Check credentials.'
        }
    
    # Test 2: List objects in bucket
    try:
        response = b2_client.list_objects_v2(
            Bucket=B2_CONFIG['BUCKET_NAME'],
            MaxKeys=10
        )
        objects = [obj['Key'] for obj in response.get('Contents', [])]
        results['tests']['list_objects'] = {
            'success': True,
            'count': response.get('KeyCount', 0),
            'objects': objects,
            'message': f"Successfully listed {response.get('KeyCount', 0)} objects in bucket."
        }
    except Exception as e:
        results['tests']['list_objects'] = {
            'success': False,
            'error': str(e),
            'message': 'Failed to list objects. Check bucket permissions.'
        }
    
    # Test 3: Generate signed URL
    try:
        test_key = 'test-signed-url.txt'
        signed_url = generate_signed_url(test_key, expiration=3600)
        results['tests']['generate_signed_url'] = {
            'success': signed_url is not None,
            'url': signed_url,
            'message': 'Successfully generated signed URL.' if signed_url else 'Failed to generate signed URL.'
        }
    except Exception as e:
        results['tests']['generate_signed_url'] = {
            'success': False,
            'error': str(e),
            'message': 'Failed to generate signed URL.'
        }
    
    # Test 4: Check if bucket is public
    try:
        test_url = f"{B2_CONFIG['CDN_URL']}/test-public.txt"
        response = requests.head(test_url, timeout=5)
        results['tests']['public_access'] = {
            'success': response.status_code == 200,
            'status_code': response.status_code,
            'message': 'Bucket appears to be PUBLIC' if response.status_code == 200 else 'Bucket is PRIVATE (good for security)'
        }
    except:
        results['tests']['public_access'] = {
            'success': False,
            'message': 'Bucket is PRIVATE (signed URLs required)'
        }
    
    # Test 5: Get existing B2 images count
    results['tests']['stored_images'] = {
        'success': True,
        'count': len(data_store.b2_images),
        'message': f"{len(data_store.b2_images)} images recorded in database."
    }
    
    return jsonify(results), 200

@app.route('/api/b2/images', methods=['GET'])
@jwt_required()
def get_b2_images():
    """Get all B2 images with fresh signed URLs"""
    try:
        images = []
        for img in data_store.b2_images[-50:]:  # Last 50 images
            img_copy = img.copy()
            # Generate fresh signed URL
            fresh_url = generate_signed_url(img['s3_key'], expiration=86400)
            if fresh_url:
                img_copy['signed_url'] = fresh_url
            images.append(img_copy)
        
        return jsonify(images), 200
    except Exception as e:
        logger.error(f"Error getting B2 images: {e}")
        return jsonify([]), 200

# ==================== PRODUCT ROUTES ====================
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with fresh signed URLs"""
    try:
        search = request.args.get('search', '').lower()
        category = request.args.get('category')
        in_stock = request.args.get('in_stock', '').lower() == 'true'
        
        products = data_store.products
        
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
            if product.get('s3_key'):
                fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
                if fresh_url:
                    product_copy['image'] = fresh_url
                    product_copy['image_expires'] = (datetime.now() + timedelta(days=1)).isoformat()
            products_copy.append(product_copy)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products/<int:product_id>', methods=['GET'])
@jwt_required()
def get_product(product_id):
    """Get single product with fresh signed URL"""
    try:
        product = next((p for p in data_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Create a copy to avoid modifying original
        product_copy = product.copy()
        
        # Generate fresh signed URL if we have s3_key
        if product.get('s3_key'):
            fresh_url = generate_signed_url(product['s3_key'], expiration=86400)
            if fresh_url:
                product_copy['image'] = fresh_url
                product_copy['image_expires'] = (datetime.now() + timedelta(days=1)).isoformat()
        
        return jsonify(product_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting product {product_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product with B2 signed URL"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['name', 'category', 'buyPrice', 'minSellPrice', 'maxSellPrice', 'sizes']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Calculate total stock
        total_stock = 0
        if data['sizes']:
            total_stock = sum([int(v) for v in data['sizes'].values() if v and int(v) > 0])
        
        # Extract S3 key from image URL
        image_url = data.get('image', '')
        s3_key = extract_s3_key_from_url(image_url)
        
        # Generate fresh signed URL
        signed_url = None
        if s3_key:
            signed_url = generate_signed_url(s3_key, expiration=604800)
        
        product = {
            'id': int(datetime.now().timestamp() * 1000),
            'name': data['name'].strip(),
            'sku': data.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}"),
            'category': data['category'],
            'color': data.get('color', '').strip(),
            'sizes': data['sizes'],
            'buyPrice': float(data['buyPrice']),
            'minSellPrice': float(data['minSellPrice']),
            'maxSellPrice': float(data['maxSellPrice']),
            'description': data.get('description', '').strip(),
            'image': signed_url or image_url,
            'cdn_url': f"{B2_CONFIG['CDN_URL']}/{s3_key}" if s3_key else None,
            's3_key': s3_key,
            'totalStock': total_stock,
            'dateAdded': datetime.now().isoformat(),
            'lastUpdated': datetime.now().isoformat(),
            'storage': {
                'type': 'backblaze-b2',
                'bucket_id': B2_CONFIG['BUCKET_ID'],
                'bucket_name': B2_CONFIG['BUCKET_NAME'],
                'endpoint': B2_CONFIG['ENDPOINT'],
                'cdn_url': B2_CONFIG['CDN_URL'],
                's3_key': s3_key,
                'uploadedAt': datetime.now().isoformat(),
                'expiresAt': (datetime.now() + timedelta(days=7)).isoformat()
            }
        }
        
        data_store.products.append(product)
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'New product added: {product["name"]}',
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        
        # Trim notifications
        if len(data_store.notifications) > 100:
            data_store.notifications = data_store.notifications[:100]
        
        data_store.save_data()
        
        logger.info(f"Product created: {product['name']} (ID: {product['id']})")
        
        return jsonify(product), 201
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update existing product"""
    try:
        data = request.get_json()
        
        product = next((p for p in data_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Update fields
        updatable_fields = ['name', 'sku', 'category', 'color', 'sizes', 'buyPrice', 
                           'minSellPrice', 'maxSellPrice', 'description', 'image']
        
        for field in updatable_fields:
            if field in data:
                product[field] = data[field]
        
        # Update S3 key if image changed
        if 'image' in data:
            s3_key = extract_s3_key_from_url(data['image'])
            if s3_key:
                product['s3_key'] = s3_key
                product['cdn_url'] = f"{B2_CONFIG['CDN_URL']}/{s3_key}"
        
        # Recalculate total stock
        if 'sizes' in data:
            total_stock = 0
            for stock in data['sizes'].values():
                total_stock += int(stock) if stock > 0 else 0
            product['totalStock'] = total_stock
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        data_store.save_data()
        
        logger.info(f"Product updated: {product['name']} (ID: {product_id})")
        
        return jsonify(product), 200
        
    except Exception as e:
        logger.error(f"Error updating product {product_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    try:
        product = next((p for p in data_store.products if p['id'] == product_id), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        data_store.products = [p for p in data_store.products if p['id'] != product_id]
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f'Product deleted: {product["name"]}',
            'type': 'warning',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_data()
        
        logger.info(f"Product deleted: {product['name']} (ID: {product_id})")
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error deleting product {product_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/categories', methods=['GET'])
@jwt_required()
def get_categories():
    """Get all unique product categories"""
    try:
        categories = list(set([p.get('category') for p in data_store.products if p.get('category')]))
        categories.sort()
        return jsonify(categories), 200
    except Exception as e:
        logger.error(f"Error getting categories: {e}")
        return jsonify([]), 200

@app.route('/api/products/colors', methods=['GET'])
@jwt_required()
def get_colors():
    """Get all unique product colors"""
    try:
        colors = list(set([p.get('color') for p in data_store.products if p.get('color')]))
        colors.sort()
        return jsonify(colors), 200
    except Exception as e:
        logger.error(f"Error getting colors: {e}")
        return jsonify([]), 200

@app.route('/api/products/sizes', methods=['GET'])
@jwt_required()
def get_sizes():
    """Get size range"""
    return jsonify(list(range(CONFIG['SIZE_RANGE']['MIN'], CONFIG['SIZE_RANGE']['MAX'] + 1))), 200

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
        
        user = next((u for u in data_store.users if u['email'] == email), None)
        
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
        user = next((u for u in data_store.users if str(u['id']) == current_user_id), None)
        
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

# ==================== SALES ROUTES ====================
@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales with optional time period filtering"""
    try:
        period = request.args.get('period', 'today')
        
        sales = data_store.sales
        now = datetime.now()
        
        if period == 'today':
            today_start = datetime(now.year, now.month, now.day).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= today_start]
        elif period == '7days':
            week_ago = (now - timedelta(days=7)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= week_ago]
        elif period == '1month':
            month_ago = (now - timedelta(days=30)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= month_ago]
        elif period == '6months':
            six_months_ago = (now - timedelta(days=180)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= six_months_ago]
        elif period == '12months':
            year_ago = (now - timedelta(days=365)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= year_ago]
        
        # Sort by timestamp (newest first)
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        return jsonify(sales), 200
        
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Record new sale"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['productId', 'size', 'quantity', 'unitPrice', 'totalAmount', 'totalProfit']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Get product
        product = next((p for p in data_store.products if p['id'] == data['productId']), None)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        size_key = str(data['size'])
        if size_key not in product['sizes'] or product['sizes'][size_key] < data['quantity']:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Update product stock
        product['sizes'][size_key] -= data['quantity']
        if product['sizes'][size_key] < 0:
            product['sizes'][size_key] = 0
        
        # Recalculate total stock
        total_stock = 0
        for stock in product['sizes'].values():
            total_stock += stock if stock > 0 else 0
        product['totalStock'] = total_stock
        product['lastUpdated'] = datetime.now().isoformat()
        
        # Create sale record
        sale = {
            'id': int(datetime.now().timestamp() * 1000),
            **data,
            'productName': product['name'],
            'productSKU': product.get('sku', ''),
            'unitCost': float(product['buyPrice']),
            'timestamp': datetime.now().isoformat(),
            'statementGenerated': True,
            'statementId': f"{int(datetime.now().timestamp() * 1000)}-SALE"
        }
        
        data_store.sales.insert(0, sale)
        
        # Generate sale statement
        statement = {
            'id': sale['statementId'],
            'saleId': sale['id'],
            'timestamp': datetime.now().isoformat(),
            'productName': product['name'],
            'productSKU': product.get('sku', ''),
            'productColor': product.get('color', 'N/A'),
            'category': product.get('category', 'N/A'),
            'size': data['size'],
            'quantity': data['quantity'],
            'unitPrice': float(data['unitPrice']),
            'totalAmount': float(data['totalAmount']),
            'totalProfit': float(data['totalProfit']),
            'customerName': data.get('customerName', 'Walk-in Customer'),
            'isBargain': data.get('isBargain', False),
            'notes': data.get('notes', 'No additional notes')
        }
        
        data_store.sale_statements.insert(0, statement)
        
        # Trim statements
        if len(data_store.sale_statements) > 100:
            data_store.sale_statements = data_store.sale_statements[:100]
        
        # Record monthly category sales
        month_key = datetime.now().strftime('%Y-%m')
        
        if month_key not in data_store.monthly_category_sales:
            data_store.monthly_category_sales[month_key] = {}
        
        category = product.get('category', 'Other')
        
        if category not in data_store.monthly_category_sales[month_key]:
            data_store.monthly_category_sales[month_key][category] = {
                'revenue': 0,
                'quantity': 0,
                'profit': 0
            }
        
        data_store.monthly_category_sales[month_key][category]['revenue'] += float(data['totalAmount'])
        data_store.monthly_category_sales[month_key][category]['quantity'] += data['quantity']
        data_store.monthly_category_sales[month_key][category]['profit'] += float(data['totalProfit'])
        
        # Add notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': f"Sale recorded: {product['name']} ({data['quantity']} × Size {data['size']})",
            'type': 'success',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        
        data_store.save_data()
        
        logger.info(f"Sale recorded: {sale['id']} - {product['name']} x{data['quantity']}")
        
        return jsonify({
            'sale': sale,
            'statement': statement
        }), 201
        
    except Exception as e:
        logger.error(f"Error creating sale: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/statements', methods=['GET'])
@jwt_required()
def get_sale_statements():
    """Get all sale statements"""
    try:
        return jsonify(data_store.sale_statements), 200
    except Exception as e:
        logger.error(f"Error getting sale statements: {e}")
        return jsonify([]), 200

@app.route('/api/sales/statements/<int:sale_id>', methods=['GET'])
@jwt_required()
def get_sale_statement(sale_id):
    """Get specific sale statement"""
    try:
        statement = next((s for s in data_store.sale_statements if s['saleId'] == sale_id), None)
        
        if statement:
            return jsonify(statement), 200
        
        return jsonify({'error': 'Statement not found'}), 404
        
    except Exception as e:
        logger.error(f"Error getting sale statement {sale_id}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/statements/<int:sale_id>/download', methods=['GET'])
@jwt_required()
def download_sale_statement(sale_id):
    """Download sale statement as text file"""
    try:
        statement = next((s for s in data_store.sale_statements if s['saleId'] == sale_id), None)
        
        if not statement:
            return jsonify({'error': 'Statement not found'}), 404
        
        content = f"""
SALE STATEMENT
================
Statement ID: {statement['id']}
Sale ID: {statement['saleId']}
Date: {datetime.fromisoformat(statement['timestamp']).strftime('%B %d, %Y at %I:%M %p')}

PRODUCT DETAILS
---------------
Product: {statement['productName']}
SKU: {statement['productSKU']}
Category: {statement['category']}
Color: {statement['productColor']}
Size: {statement['size']}
Quantity: {statement['quantity']}

FINANCIAL DETAILS
-----------------
Unit Price: KES {statement['unitPrice']:,.2f}
Total Amount: KES {statement['totalAmount']:,.2f}
Total Profit: KES {statement['totalProfit']:,.2f}
Sale Type: {'Bargain Sale' if statement['isBargain'] else 'Regular Sale'}

CUSTOMER DETAILS
----------------
Customer: {statement['customerName']}

ADDITIONAL NOTES
----------------
{statement['notes']}

--- End of Statement ---
Karanja Shoe Store Management System
Created: February 9, 2026
Backblaze B2 Bucket: {B2_CONFIG['BUCKET_NAME']} (Created: {B2_CONFIG['CREATED_DATE']})
Bucket Type: {B2_CONFIG['TYPE']}
Current Files: {B2_CONFIG['CURRENT_FILES']} ({B2_CONFIG['CURRENT_SIZE']})
        """
        
        return send_file(
            io.BytesIO(content.encode('utf-8')),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f"sale_statement_{statement['id']}.txt"
        ), 200
        
    except Exception as e:
        logger.error(f"Error downloading sale statement {sale_id}: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== DASHBOARD STATS ROUTES ====================
@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics for a specific time period"""
    try:
        period = request.args.get('period', 'today')
        
        sales = data_store.sales
        now = datetime.now()
        
        # Filter sales by period
        if period == 'today':
            start_date = datetime(now.year, now.month, now.day).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        elif period == '7days':
            start_date = (now - timedelta(days=7)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        elif period == '1month':
            start_date = (now - timedelta(days=30)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        elif period == '6months':
            start_date = (now - timedelta(days=180)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        elif period == '12months':
            start_date = (now - timedelta(days=365)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        
        # Calculate stats
        total_sales = sum([s['totalAmount'] for s in sales])
        total_profit = sum([s['totalProfit'] for s in sales])
        total_stock = sum([p['totalStock'] for p in data_store.products])
        total_products = len(data_store.products)
        
        # Calculate today's stats
        today_start = datetime(now.year, now.month, now.day).isoformat()
        today_sales = [s for s in data_store.sales if s.get('timestamp', '') >= today_start]
        today_revenue = sum([s['totalAmount'] for s in today_sales])
        today_profit = sum([s['totalProfit'] for s in today_sales])
        today_items = sum([s['quantity'] for s in today_sales])
        
        # Calculate sales trends
        days_to_show = 7
        if period == '1month':
            days_to_show = 30
        elif period == '6months':
            days_to_show = 180
        elif period == '12months':
            days_to_show = 365
        
        sales_trends = []
        for i in range(days_to_show - 1, -1, -max(1, days_to_show // 30)):
            date = now - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            date_label = date.strftime('%b %d')
            
            daily_sales = [s for s in sales if s.get('timestamp', '')[:10] == date_str]
            daily_total = sum([s['totalAmount'] for s in daily_sales])
            
            sales_trends.append({
                'date': date_label,
                'amount': daily_total
            })
        
        # Calculate top products
        product_sales = {}
        for sale in sales:
            product_name = sale['productName']
            if product_name not in product_sales:
                product_sales[product_name] = 0
            product_sales[product_name] += sale['quantity']
        
        top_products = []
        for product_name, quantity in sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]:
            top_products.append({
                'name': product_name,
                'quantity': quantity
            })
        
        # Get today's statement
        today_statement = next((s for s in data_store.daily_statements 
                               if s.get('date', '')[:10] == datetime.now().strftime('%Y-%m-%d')), None)
        
        return jsonify({
            'totalSales': total_sales,
            'totalProfit': total_profit,
            'totalStock': total_stock,
            'totalProducts': total_products,
            'todaySales': today_revenue,
            'todayProfit': today_profit,
            'todayItems': today_items,
            'salesTrends': sales_trends,
            'topProducts': top_products,
            'dailyStatement': today_statement
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {e}")
        logger.error(traceback.format_exc())
        return jsonify({
            'totalSales': 0,
            'totalProfit': 0,
            'totalStock': 0,
            'totalProducts': 0,
            'todaySales': 0,
            'todayProfit': 0,
            'todayItems': 0,
            'salesTrends': [],
            'topProducts': [],
            'dailyStatement': None
        }), 200

@app.route('/api/dashboard/daily-statement', methods=['POST'])
@jwt_required()
def generate_daily_statement():
    """Generate daily sales statement"""
    try:
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        
        # Check if statement already exists
        existing = next((s for s in data_store.daily_statements 
                        if s.get('date', '')[:10] == today_str), None)
        
        if existing:
            return jsonify(existing), 200
        
        # Get today's sales
        today_start = datetime(now.year, now.month, now.day).isoformat()
        today_sales = [s for s in data_store.sales if s.get('timestamp', '') >= today_start]
        
        total_revenue = sum([s['totalAmount'] for s in today_sales])
        total_profit = sum([s['totalProfit'] for s in today_sales])
        total_items = sum([s['quantity'] for s in today_sales])
        bargain_sales = len([s for s in today_sales if s.get('isBargain', False)])
        
        # Category breakdown
        category_breakdown = {}
        for sale in today_sales:
            product = next((p for p in data_store.products if p['id'] == sale['productId']), None)
            if product:
                category = product.get('category', 'Other')
                if category not in category_breakdown:
                    category_breakdown[category] = {
                        'revenue': 0,
                        'items': 0,
                        'profit': 0
                    }
                category_breakdown[category]['revenue'] += sale['totalAmount']
                category_breakdown[category]['items'] += sale['quantity']
                category_breakdown[category]['profit'] += sale['totalProfit']
        
        statement = {
            'id': int(datetime.now().timestamp() * 1000),
            'date': now.isoformat(),
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'totalItems': total_items,
            'bargainSales': bargain_sales,
            'salesCount': len(today_sales),
            'avgSaleValue': total_revenue / len(today_sales) if today_sales else 0,
            'categoryBreakdown': category_breakdown,
            'generatedAt': now.isoformat()
        }
        
        data_store.daily_statements.insert(0, statement)
        
        # Trim statements
        if len(data_store.daily_statements) > 30:
            data_store.daily_statements = data_store.daily_statements[:30]
        
        data_store.save_data()
        
        logger.info(f"Daily statement generated for {today_str}")
        
        return jsonify(statement), 201
        
    except Exception as e:
        logger.error(f"Error generating daily statement: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/dashboard/daily-statements', methods=['GET'])
@jwt_required()
def get_daily_statements():
    """Get all daily statements"""
    try:
        return jsonify(data_store.daily_statements), 200
    except Exception as e:
        logger.error(f"Error getting daily statements: {e}")
        return jsonify([]), 200

@app.route('/api/dashboard/daily-statement/download', methods=['GET'])
@jwt_required()
def download_daily_statement():
    """Download daily statement as CSV"""
    try:
        date = request.args.get('date')
        
        if date:
            statement = next((s for s in data_store.daily_statements 
                             if s.get('date', '')[:10] == date), None)
        else:
            # Get today's statement
            today_str = datetime.now().strftime('%Y-%m-%d')
            statement = next((s for s in data_store.daily_statements 
                             if s.get('date', '')[:10] == today_str), None)
        
        if not statement:
            return jsonify({'error': 'Statement not found'}), 404
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Daily Sales Statement'])
        writer.writerow([])
        writer.writerow(['Date:', datetime.fromisoformat(statement['date']).strftime('%B %d, %Y')])
        writer.writerow(['Total Revenue:', f"KES {statement['totalRevenue']:,.2f}"])
        writer.writerow(['Total Profit:', f"KES {statement['totalProfit']:,.2f}"])
        writer.writerow(['Total Items Sold:', statement['totalItems']])
        writer.writerow(['Number of Sales:', statement['salesCount']])
        writer.writerow(['Bargain Sales:', statement['bargainSales']])
        writer.writerow(['Average Sale Value:', f"KES {statement['avgSaleValue']:,.2f}"])
        writer.writerow([])
        writer.writerow(['Category Breakdown'])
        writer.writerow(['Category', 'Revenue', 'Items Sold', 'Profit'])
        
        for category, data in statement['categoryBreakdown'].items():
            writer.writerow([
                category,
                f"KES {data['revenue']:,.2f}",
                data['items'],
                f"KES {data['profit']:,.2f}"
            ])
        
        writer.writerow([])
        writer.writerow(['---'])
        writer.writerow(['Generated by: Karanja Shoe Store Management System'])
        writer.writerow(['Created: February 9, 2026'])
        writer.writerow([f'Backblaze B2 Bucket: {B2_CONFIG["BUCKET_NAME"]}'])
        writer.writerow([f'Bucket Created: {B2_CONFIG["CREATED_DATE"]}'])
        writer.writerow([f'Bucket Type: {B2_CONFIG["TYPE"]}'])
        writer.writerow([f'Current Files: {B2_CONFIG["CURRENT_FILES"]} ({B2_CONFIG["CURRENT_SIZE"]})'])
        
        output.seek(0)
        
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8')),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f"sales_statement_{statement['date'][:10]}.csv"
        ), 200
        
    except Exception as e:
        logger.error(f"Error downloading daily statement: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== FINANCE ROUTES ====================
@app.route('/api/finance/overview', methods=['GET'])
@jwt_required()
def get_finance_overview():
    """Get financial overview"""
    try:
        period = request.args.get('period', '7days')
        
        sales = data_store.sales
        now = datetime.now()
        
        # Filter sales by period
        if period == '7days':
            start_date = (now - timedelta(days=7)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        elif period == '30days':
            start_date = (now - timedelta(days=30)).isoformat()
            sales = [s for s in sales if s.get('timestamp', '') >= start_date]
        
        total_revenue = sum([s['totalAmount'] for s in sales])
        total_cost = sum([s.get('unitCost', 0) * s['quantity'] for s in sales])
        total_profit = sum([s['totalProfit'] for s in sales])
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # Daily revenue for chart
        days_to_show = 7 if period == '7days' else 30
        
        daily_revenue = []
        for i in range(days_to_show - 1, -1, -1):
            date = now - timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            date_label = date.strftime('%b %d')
            
            daily_sales = [s for s in sales if s.get('timestamp', '')[:10] == date_str]
            daily_total = sum([s['totalAmount'] for s in daily_sales])
            
            daily_revenue.append({
                'date': date_label,
                'amount': daily_total
            })
        
        return jsonify({
            'totalRevenue': total_revenue,
            'totalCost': total_cost,
            'totalProfit': total_profit,
            'profitMargin': profit_margin,
            'dailyRevenue': daily_revenue
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting finance overview: {e}")
        return jsonify({
            'totalRevenue': 0,
            'totalCost': 0,
            'totalProfit': 0,
            'profitMargin': 0,
            'dailyRevenue': []
        }), 200

# ==================== STOCK ANALYSIS ROUTES ====================
@app.route('/api/stock/analysis', methods=['GET'])
@jwt_required()
def get_stock_analysis():
    """Get stock analysis and category rankings"""
    try:
        period = request.args.get('period', 'current')
        
        rankings = []
        
        if period == 'current':
            month_key = datetime.now().strftime('%Y-%m')
            categories_data = data_store.monthly_category_sales.get(month_key, {})
        elif period == 'last':
            last_month = datetime.now() - timedelta(days=30)
            month_key = last_month.strftime('%Y-%m')
            categories_data = data_store.monthly_category_sales.get(month_key, {})
        elif period == 'last3':
            categories_data = {}
            for i in range(3):
                date = datetime.now() - timedelta(days=30 * i)
                month_key = date.strftime('%Y-%m')
                month_data = data_store.monthly_category_sales.get(month_key, {})
                
                for category, data in month_data.items():
                    if category not in categories_data:
                        categories_data[category] = {
                            'revenue': 0,
                            'quantity': 0,
                            'profit': 0
                        }
                    categories_data[category]['revenue'] += data['revenue']
                    categories_data[category]['quantity'] += data['quantity']
                    categories_data[category]['profit'] += data['profit']
        else:
            categories_data = {}
            for month_key, month_data in data_store.monthly_category_sales.items():
                for category, data in month_data.items():
                    if category not in categories_data:
                        categories_data[category] = {
                            'revenue': 0,
                            'quantity': 0,
                            'profit': 0
                        }
                    categories_data[category]['revenue'] += data['revenue']
                    categories_data[category]['quantity'] += data['quantity']
                    categories_data[category]['profit'] += data['profit']
        
        total_revenue = sum([c['revenue'] for c in categories_data.values()])
        
        for category, data in categories_data.items():
            market_share = (data['revenue'] / total_revenue * 100) if total_revenue > 0 else 0
            
            # Determine demand level
            avg_monthly_revenue = data['revenue']
            if period == 'last3':
                avg_monthly_revenue = data['revenue'] / 3
            
            if avg_monthly_revenue > 50000:
                demand_level = 'Very High'
            elif avg_monthly_revenue > 20000:
                demand_level = 'High'
            elif avg_monthly_revenue > 5000:
                demand_level = 'Medium'
            elif avg_monthly_revenue > 1000:
                demand_level = 'Low'
            else:
                demand_level = 'Very Low'
            
            rankings.append({
                'category': category,
                'revenue': data['revenue'],
                'quantity': data['quantity'],
                'profit': data['profit'],
                'marketShare': round(market_share, 1),
                'demandLevel': demand_level,
                'avgMonthlyRevenue': avg_monthly_revenue
            })
        
        # Sort by revenue (highest first)
        rankings.sort(key=lambda x: x['revenue'], reverse=True)
        
        return jsonify(rankings), 200
        
    except Exception as e:
        logger.error(f"Error getting stock analysis: {e}")
        return jsonify([]), 200

@app.route('/api/stock/alerts', methods=['GET'])
@jwt_required()
def get_stock_alerts():
    """Get stock alerts"""
    try:
        alerts = []
        
        # Low stock alerts
        for product in data_store.products:
            if product.get('sizes'):
                for size, stock in product['sizes'].items():
                    if stock > 0 and stock <= CONFIG['LOW_STOCK_THRESHOLD']:
                        alerts.append({
                            'type': 'low_stock',
                            'product': product['name'],
                            'size': size,
                            'stock': stock,
                            'message': f"{product['name']} (Size {size}) is running low - only {stock} left!"
                        })
            
            # Old stock alerts
            if product.get('dateAdded'):
                try:
                    product_date = datetime.fromisoformat(product['dateAdded'])
                    days_in_stock = (datetime.now() - product_date).days
                    
                    if days_in_stock >= CONFIG['OLD_STOCK_DAYS'] and product.get('totalStock', 0) > 0:
                        alerts.append({
                            'type': 'old_stock',
                            'product': product['name'],
                            'daysInStock': days_in_stock,
                            'stock': product['totalStock'],
                            'message': f"{product['name']} has been in stock for {days_in_stock} days - consider promotions!"
                        })
                except:
                    pass
        
        return jsonify(alerts), 200
        
    except Exception as e:
        logger.error(f"Error getting stock alerts: {e}")
        return jsonify([]), 200

@app.route('/api/stock/budget-plan', methods=['GET'])
@jwt_required()
def get_budget_plan():
    """Get bi-weekly budget plan"""
    try:
        two_weeks_ago = (datetime.now() - timedelta(days=14)).isoformat()
        
        recent_sales = [s for s in data_store.sales if s.get('timestamp', '') >= two_weeks_ago]
        
        total_revenue = sum([s['totalAmount'] for s in recent_sales])
        total_profit = sum([s['totalProfit'] for s in recent_sales])
        avg_daily_revenue = total_revenue / 14 if recent_sales else 0
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # Calculate budget based on profit
        weekly_budget = max(total_profit * 0.3, 1000)
        
        # Get category performance
        rankings_response = get_stock_analysis()
        rankings = rankings_response.json if hasattr(rankings_response, 'json') else []
        
        high_demand = [c for c in rankings if 'High' in c.get('demandLevel', '')][:3]
        low_demand = [c for c in rankings if 'Low' in c.get('demandLevel', '')][:3]
        
        # Restock recommendations
        restock_recommendations = []
        for product in data_store.products:
            product_sales = [s for s in recent_sales if s['productId'] == product['id']]
            sales_count = sum([s['quantity'] for s in product_sales])
            
            if product.get('dateAdded'):
                try:
                    days_in_stock = (datetime.now() - datetime.fromisoformat(product['dateAdded'])).days
                    days_in_stock = max(days_in_stock, 1)
                    
                    if sales_count > 0 and product.get('totalStock', 0) < 5 and days_in_stock < 30:
                        sales_velocity = sales_count / days_in_stock
                        if sales_velocity > 0.1:
                            restock_recommendations.append({
                                'product': product['name'],
                                'currentStock': product['totalStock'],
                                'salesVelocity': round(sales_velocity, 2),
                                'recommendation': f"Restock {int(sales_velocity * 14)} units for next 2 weeks"
                            })
                except:
                    pass
        
        # Budget allocation
        budget_allocation = [
            {'category': 'High Demand Products', 'percentage': 50, 'amount': weekly_budget * 0.5},
            {'category': 'Restock Fast Movers', 'percentage': 30, 'amount': weekly_budget * 0.3},
            {'category': 'New Opportunities', 'percentage': 15, 'amount': weekly_budget * 0.15},
            {'category': 'Emergency Buffer', 'percentage': 5, 'amount': weekly_budget * 0.05}
        ]
        
        return jsonify({
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'avgDailyRevenue': avg_daily_revenue,
            'profitMargin': round(profit_margin, 1),
            'weeklyBudget': weekly_budget,
            'highDemand': high_demand,
            'lowDemand': low_demand,
            'restockRecommendations': restock_recommendations[:5],
            'budgetAllocation': budget_allocation,
            'recommendation': f"Based on last 2 weeks' profit of KES {total_profit:,.2f}, allocate KES {weekly_budget:,.2f} for inventory." if total_profit > 0 else "Not enough data for budget planning. Start making more sales."
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting budget plan: {e}")
        return jsonify({
            'totalRevenue': 0,
            'totalProfit': 0,
            'avgDailyRevenue': 0,
            'profitMargin': 0,
            'weeklyBudget': 1000,
            'highDemand': [],
            'lowDemand': [],
            'restockRecommendations': [],
            'budgetAllocation': [],
            'recommendation': 'No budget recommendations available yet'
        }), 200

# ==================== BUSINESS PLAN ROUTES ====================
@app.route('/api/business-plan', methods=['GET'])
@jwt_required()
def get_business_plan():
    """Get business plan calculations"""
    try:
        total_profit = sum([s['totalProfit'] for s in data_store.sales])
        total_revenue = sum([s['totalAmount'] for s in data_store.sales])
        
        plan = {
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'tithe': total_profit * (CONFIG['TITHE_PERCENTAGE'] / 100),
            'savings': total_profit * (CONFIG['SAVINGS_PERCENTAGE'] / 100),
            'restock': total_profit * (CONFIG['RESTOCK_PERCENTAGE'] / 100),
            'deductions': total_profit * (CONFIG['DEDUCTIONS_PERCENTAGE'] / 100),
            'personalIncome': total_profit * (CONFIG['PERSONAL_INCOME_PERCENTAGE'] / 100)
        }
        
        # Business health score
        revenue_score = min(100, (total_revenue / CONFIG['BUSINESS_HEALTH_GOAL']) * 100)
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        profit_score = min(100, profit_margin * 2)
        
        stock_value = sum([p['totalStock'] * p['buyPrice'] for p in data_store.products])
        inventory_score = min(100, (stock_value / 50000) * 100)
        
        health_score = int((revenue_score * 0.4) + (profit_score * 0.3) + (inventory_score * 0.3))
        
        if health_score >= 85:
            status = 'Excellent'
        elif health_score >= 70:
            status = 'Very Good'
        elif health_score >= 50:
            status = 'Good'
        elif health_score >= 30:
            status = 'Fair'
        else:
            status = 'Needs Improvement'
        
        plan['healthScore'] = health_score
        plan['healthStatus'] = status
        plan['healthBreakdown'] = {
            'revenue': revenue_score,
            'profit': profit_score,
            'inventory': inventory_score
        }
        
        return jsonify(plan), 200
        
    except Exception as e:
        logger.error(f"Error getting business plan: {e}")
        return jsonify({
            'totalRevenue': 0,
            'totalProfit': 0,
            'tithe': 0,
            'savings': 0,
            'restock': 0,
            'deductions': 0,
            'personalIncome': 0,
            'healthScore': 0,
            'healthStatus': 'Needs Improvement',
            'healthBreakdown': {'revenue': 0, 'profit': 0, 'inventory': 0}
        }), 200

# ==================== NOTIFICATION ROUTES ====================
@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    try:
        unread_only = request.args.get('unread', '').lower() == 'true'
        
        notifications = data_store.notifications
        
        if unread_only:
            notifications = [n for n in notifications if not n.get('read', False)]
        
        return jsonify(notifications[:50]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        notification = next((n for n in data_store.notifications if n['id'] == notification_id), None)
        
        if notification:
            notification['read'] = True
            data_store.save_data()
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
        for notification in data_store.notifications:
            notification['read'] = True
        
        data_store.save_data()
        
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error marking all notifications read: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_unread_notification_count():
    """Get unread notification count"""
    try:
        unread_count = len([n for n in data_store.notifications if not n.get('read', False)])
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return jsonify({'count': 0}), 200

# ==================== SETTINGS ROUTES ====================
@app.route('/api/settings', methods=['GET'])
@jwt_required()
def get_settings():
    """Get application settings"""
    try:
        return jsonify(data_store.settings), 200
    except Exception as e:
        logger.error(f"Error getting settings: {e}")
        return jsonify({}), 200

@app.route('/api/settings', methods=['PUT'])
@jwt_required()
def update_settings():
    """Update application settings"""
    try:
        data = request.get_json()
        data_store.settings.update(data)
        data_store.save_data()
        return jsonify(data_store.settings), 200
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
            'products': len(data_store.products),
            'sales': len(data_store.sales),
            'notifications': len(data_store.notifications),
            'b2_images': len(data_store.b2_images)
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
def init_data():
    """Initialize sample data if no products exist"""
    try:
        if len(data_store.products) == 0:
            # Add welcome notification
            notification = {
                'id': int(datetime.now().timestamp() * 1000),
                'message': f'Welcome to Karanja Shoe Store! Connected to B2 bucket: {B2_CONFIG["BUCKET_NAME"]} (Created: {B2_CONFIG["CREATED_DATE"]})',
                'type': 'info',
                'timestamp': datetime.now().isoformat(),
                'read': False
            }
            data_store.notifications.insert(0, notification)
            data_store.save_data()
            logger.info("Sample data initialized")
    except Exception as e:
        logger.error(f"Error initializing data: {e}")

# Initialize sample data
init_data()

# ==================== CATCH-ALL ROUTE FOR SPA ====================
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API routes"""
    try:
        if path.startswith('api/'):
            return jsonify({'error': 'API endpoint not found'}), 404
        
        if os.path.exists('index.html'):
            with open('index.html', 'r') as f:
                return render_template_string(f.read())
        else:
            return jsonify({
                'error': 'index.html not found',
                'message': 'Please ensure index.html is in the same directory as app.py',
                'b2_bucket': B2_CONFIG['BUCKET_NAME'],
                'b2_created': B2_CONFIG['CREATED_DATE'],
                'status': 'Backend is running'
            }), 200
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        return jsonify({
            'error': 'Could not load index.html',
            'message': str(e),
            'b2_bucket': B2_CONFIG['BUCKET_NAME'],
            'status': 'Backend is running'
        }), 200

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 20MB'}), 413

# ==================== RUN APPLICATION ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
