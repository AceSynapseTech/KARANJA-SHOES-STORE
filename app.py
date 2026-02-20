from flask import Flask, request, jsonify, send_file, send_from_directory, make_response, abort
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, verify_jwt_in_request
from datetime import datetime, timedelta
import json
import os
from supabase import create_client, Client
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
        # Create a simple placeholder
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (300, 300), color=(102, 126, 234))
            draw = ImageDraw.Draw(img)
            draw.text((150, 150), "No Image", fill="white", anchor="mm")
            img.save(placeholder_path)
            logger.info("✓ Created placeholder image")
        except:
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

# ==================== SUPABASE CONFIGURATION ====================
SUPABASE_URL = "https://vvblvnwn1mngqefrgezc.supabase.co"
SUPABASE_KEY = "sb_publishable_VVb-vLNwn1MNGQeFRgezCg_MqotUN5t"  # Your anon/publishable key
SUPABASE_SECRET = "sb_secret_K31LtkiAsTufmOKCgRwvlA_Zr8OcMzX"  # Your secret key

# Buckets/Storage configuration
STORAGE_BUCKET = "product-images"

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✓ Supabase client initialized successfully")
    
    # Test connection by trying to list buckets
    try:
        buckets = supabase.storage.list_buckets()
        logger.info(f"✓ Successfully connected to Supabase. Available buckets: {[b['name'] for b in buckets]}")
        
        # Check if our bucket exists, if not create it
        bucket_exists = False
        for bucket in buckets:
            if bucket['name'] == STORAGE_BUCKET:
                bucket_exists = True
                logger.info(f"✓ Bucket '{STORAGE_BUCKET}' already exists")
                break
        
        if not bucket_exists:
            # Create the bucket
            supabase.storage.create_bucket(STORAGE_BUCKET, options={
                "public": False  # Keep it private for security
            })
            logger.info(f"✓ Created bucket: {STORAGE_BUCKET}")
        
        SUPABASE_AVAILABLE = True
    except Exception as e:
        logger.error(f"✗ Error accessing Supabase storage: {e}")
        SUPABASE_AVAILABLE = False
        
except Exception as e:
    logger.error(f"✗ Failed to initialize Supabase client: {e}")
    SUPABASE_AVAILABLE = False
    supabase = None

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

# ==================== SUPABASE DATA STORAGE ====================

def get_table_data(table_name):
    """Get all data from a Supabase table"""
    if not supabase:
        logger.error(f"✗ Supabase not available for {table_name}")
        return []
    try:
        logger.info(f"Fetching data from {table_name}...")
        response = supabase.table(table_name).select("*").execute()
        logger.info(f"✓ Retrieved {len(response.data)} records from {table_name}")
        return response.data
    except Exception as e:
        logger.error(f"✗ Error reading from {table_name}: {e}")
        logger.error(traceback.format_exc())
        return []

def save_table_data(table_name, data):
    """Save data to Supabase table with detailed error reporting"""
    if not supabase:
        logger.error(f"✗ Supabase not available for saving to {table_name}")
        return False
    
    try:
        logger.info(f"Attempting to save to {table_name}")
        logger.info(f"Data type: {type(data)}")
        logger.info(f"Data preview: {json.dumps(data, default=str)[:500]}")
        
        if isinstance(data, list):
            logger.info(f"Saving list of {len(data)} records")
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"✓ Successfully saved {len(data)} records to {table_name}")
        else:
            logger.info(f"Saving single record with ID: {data.get('id', 'unknown')}")
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"✓ Successfully saved single record to {table_name}")
        
        # Log the result for debugging
        if hasattr(result, 'data'):
            logger.info(f"Result data count: {len(result.data) if result.data else 0}")
            if result.data and len(result.data) > 0:
                logger.info(f"First result: {json.dumps(result.data[0], default=str)[:200]}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Error saving to {table_name}: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        logger.error(f"Error details: {traceback.format_exc()}")
        
        # Try to get more specific error info from Supabase
        if hasattr(e, 'message'):
            logger.error(f"Error message: {e.message}")
        if hasattr(e, 'details'):
            logger.error(f"Error details: {e.details}")
        if hasattr(e, 'hint'):
            logger.error(f"Error hint: {e.hint}")
        if hasattr(e, 'code'):
            logger.error(f"Error code: {e.code}")
            
        return False

def delete_table_data(table_name, record_id):
    """Delete data from Supabase table"""
    if not supabase:
        logger.error(f"✗ Supabase not available for deleting from {table_name}")
        return False
    try:
        logger.info(f"Deleting from {table_name} where id = {record_id}")
        result = supabase.table(table_name).delete().eq("id", record_id).execute()
        logger.info(f"✓ Successfully deleted from {table_name}: {record_id}")
        return True
    except Exception as e:
        logger.error(f"✗ Error deleting from {table_name}: {e}")
        logger.error(traceback.format_exc())
        return False

# ==================== SUPABASE STORAGE FOR IMAGES ====================

def upload_to_supabase_storage(file, folder="products"):
    """Upload an image to Supabase Storage"""
    if not supabase:
        return None, "Supabase not available"
    
    try:
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        file_extension = os.path.splitext(safe_filename)[1]
        unique_filename = f"{folder}/{timestamp}_{uuid.uuid4().hex}{file_extension}"
        
        # Read file data
        file.seek(0)
        file_data = file.read()
        
        # Determine content type
        content_type = file.content_type
        if not content_type:
            content_type = mimetypes.guess_type(file.filename)[0] or 'image/jpeg'
        
        logger.info(f"Uploading to Supabase: {unique_filename} ({len(file_data)} bytes)")
        
        # Upload to Supabase Storage
        response = supabase.storage.from_(STORAGE_BUCKET).upload(
            path=unique_filename,
            file=file_data,
            file_options={"content-type": content_type}
        )
        
        logger.info(f"✓ Successfully uploaded to Supabase: {unique_filename}")
        
        # Generate public URL (signed URL for private bucket)
        signed_url = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
            unique_filename, 
            expires_in=3600  # 1 hour
        )
        
        return {
            'path': unique_filename,
            'signed_url': signed_url['signedURL'] if signed_url else None,
            'proxy_url': f"/api/images/{unique_filename}"
        }, None
        
    except Exception as e:
        logger.error(f"Error uploading to Supabase: {e}")
        logger.error(traceback.format_exc())
        return None, str(e)

def delete_from_supabase_storage(path):
    """Delete an image from Supabase Storage"""
    if not supabase or not path:
        return False
    try:
        supabase.storage.from_(STORAGE_BUCKET).remove([path])
        logger.info(f"✓ Successfully deleted from Supabase: {path}")
        return True
    except Exception as e:
        logger.error(f"Error deleting from Supabase: {e}")
        return False

# ==================== IMAGE PROXY ROUTE ====================

@app.route('/api/images/<path:image_path>')
@optional_jwt_required()
def proxy_image(image_path):
    """Proxy images from Supabase storage with authentication"""
    if not supabase:
        logger.warning("Supabase not available, serving placeholder")
        return send_file('static/placeholder.png')
    
    logger.info(f"Attempting to serve image: {image_path}")
    
    try:
        # Get signed URL
        signed_url = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(
            image_path, 
            expires_in=3600
        )
        
        if not signed_url:
            logger.warning(f"Could not generate signed URL for {image_path}")
            return send_file('static/placeholder.png')
        
        # Fetch the image from Supabase
        response = requests.get(signed_url['signedURL'])
        
        if response.status_code == 200:
            # Create response with image data
            resp = make_response(response.content)
            resp.headers['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
            resp.headers['Cache-Control'] = 'public, max-age=3600'
            resp.headers['Access-Control-Allow-Origin'] = '*'
            
            logger.info(f"✓ Successfully served image via proxy: {image_path}")
            return resp
        else:
            logger.error(f"Failed to fetch image from Supabase: {response.status_code}")
            return send_file('static/placeholder.png')
            
    except Exception as e:
        logger.error(f"Error proxying image {image_path}: {e}")
        return send_file('static/placeholder.png')

# ==================== PUBLIC ENDPOINTS ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint to get products - NO LOGIN REQUIRED"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Remove sensitive data and add image URLs
        products_copy = []
        for product in products:
            product_copy = product.copy()
            product_copy.pop('buyPrice', None)
            product_copy.pop('createdBy', None)
            product_copy.pop('minSellPrice', None)
            product_copy.pop('maxSellPrice', None)
            
            # Use proxy URL for images
            if product.get('image_path'):
                product_copy['image'] = f"/api/images/{product['image_path']}"
                product_copy['imageUrl'] = f"/api/images/{product['image_path']}"
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
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
        'storage_type': 'supabase'
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

# ==================== SUPABASE UPLOAD ROUTE ====================

@app.route('/api/supabase/upload', methods=['POST'])
@jwt_required()
def upload_to_supabase():
    """Upload image to Supabase Storage"""
    if not supabase:
        logger.error("Supabase not available")
        return jsonify({'error': 'Supabase is not configured'}), 503
    
    try:
        if 'image' not in request.files:
            logger.error("No image file in request")
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            logger.error("Empty filename")
            return jsonify({'error': 'No image selected'}), 400
        
        # Log file details
        logger.info(f"Received file: {file.filename}, Content-Type: {file.content_type}")
        
        # Upload to Supabase
        result, error = upload_to_supabase_storage(file, "products")
        
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'url': f"/api/images/{result['path']}",
            'proxy_url': f"/api/images/{result['path']}",
            'path': result['path'],
            'signed_url': result['signed_url'],
            'image': f"/api/images/{result['path']}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error uploading to Supabase: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with image URLs"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Add image URLs
        products_copy = []
        for product in products:
            product_copy = product.copy()
            
            if product.get('image_path'):
                product_copy['image'] = f"/api/images/{product['image_path']}"
                product_copy['imageUrl'] = f"/api/images/{product['image_path']}"
            else:
                product_copy['image'] = '/static/placeholder.png'
            
            products_copy.append(product_copy)
        
        logger.info(f"Returning {len(products_copy)} products")
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product with detailed error handling"""
    try:
        # Log all form data for debugging
        logger.info(f"Form data keys: {list(request.form.keys())}")
        logger.info(f"Files: {list(request.files.keys()) if request.files else 'No files'}")
        
        name = request.form.get('name')
        if not name:
            return jsonify({'error': 'Product name is required'}), 400
        
        # Get other fields
        price = request.form.get('price')
        description = request.form.get('description', '')
        category = request.form.get('category', 'Uncategorized')
        color = request.form.get('color', '')
        sku = request.form.get('sku', f"KS-{str(uuid.uuid4())[:8].upper()}")
        
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
            logger.info(f"Sizes parsed: {sizes}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing sizes JSON: {e}")
            sizes = {}
        
        buy_price = request.form.get('buyPrice')
        min_sell_price = request.form.get('minSellPrice')
        max_sell_price = request.form.get('maxSellPrice')
        image_path = request.form.get('image_path')
        
        # Validate prices
        if not max_sell_price and price:
            max_sell_price = price
        if not min_sell_price and price:
            min_sell_price = price
        
        if not max_sell_price:
            return jsonify({'error': 'Price is required'}), 400
        
        # Calculate total stock
        total_stock = 0
        for size, stock in sizes.items():
            try:
                total_stock += int(stock) if stock and int(stock) > 0 else 0
            except (ValueError, TypeError):
                pass
        
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
            'storage': 'supabase'
        }
        
        if image_path:
            product['image_path'] = image_path
        
        # Log the product data
        logger.info(f"Product data to save: {json.dumps(product, default=str)}")
        
        # Check Supabase connection
        if not supabase:
            logger.error("Supabase client is None")
            return jsonify({'error': 'Supabase not connected'}), 500
        
        # Try to save
        logger.info("Attempting to save to Supabase...")
        success = save_table_data('products', product)
        
        if not success:
            logger.error("save_table_data returned False")
            return jsonify({'error': 'Failed to save to Supabase - check logs for details'}), 500
        
        # Add image URL for response
        if image_path:
            product['image'] = f"/api/images/{image_path}"
        
        logger.info(f"✓ Product created successfully: {name} (ID: {product_id})")
        
        return jsonify({
            'success': True,
            'message': 'Product created successfully in Supabase!',
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
        # Get existing product
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Update fields from form
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        color = request.form.get('color')
        sku = request.form.get('sku')
        buy_price = request.form.get('buyPrice')
        min_sell_price = request.form.get('minSellPrice')
        max_sell_price = request.form.get('maxSellPrice')
        image_path = request.form.get('image_path')
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
        
        if image_path:
            # Delete old image if exists
            if product.get('image_path'):
                delete_from_supabase_storage(product['image_path'])
            
            product['image_path'] = image_path
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        # Save to Supabase
        success = save_table_data('products', product)
        
        if not success:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
        # Add image URL for response
        if product.get('image_path'):
            product['image'] = f"/api/images/{product['image_path']}"
        
        logger.info(f"✓ Product updated successfully: {product['name']} (ID: {product_id})")
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully in Supabase!',
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
        # Get product to find image path
        products = get_table_data('products')
        product_to_delete = None
        
        for p in products:
            if p['id'] == product_id:
                product_to_delete = p
                break
        
        if not product_to_delete:
            return jsonify({'error': 'Product not found'}), 404
        
        # Delete image from storage if exists
        if product_to_delete.get('image_path'):
            delete_from_supabase_storage(product_to_delete['image_path'])
        
        # Delete from database
        success = delete_table_data('products', product_id)
        
        if not success:
            return jsonify({'error': 'Failed to delete from Supabase'}), 500
        
        logger.info(f"✓ Product deleted successfully: {product_to_delete['name']} (ID: {product_id})")
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== DASHBOARD STATS ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        products = get_table_data('products')
        sales = get_table_data('sales')
        
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
            'storage_type': 'supabase'
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
            'storage_type': 'supabase'
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
        
        # Get product
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        size_key = str(size)
        if size_key not in product['sizes'] or product['sizes'][size_key] < quantity:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Update stock
        product['sizes'][size_key] -= quantity
        if product['sizes'][size_key] < 0:
            product['sizes'][size_key] = 0
        
        total_stock = 0
        for stock in product['sizes'].values():
            total_stock += stock if stock > 0 else 0
        product['totalStock'] = total_stock
        product['lastUpdated'] = datetime.now().isoformat()
        
        # Save updated product
        save_table_data('products', product)
        
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
        
        # Save sale
        save_table_data('sales', sale)
        
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
    try:
        sales = get_table_data('sales')
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(sales), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

# ==================== STORAGE INFO ROUTE ====================

@app.route('/api/storage/info', methods=['GET'])
@jwt_required()
def get_storage_info():
    """Get Supabase storage information"""
    return jsonify({
        'provider': 'supabase',
        'bucket': STORAGE_BUCKET,
        'connected': SUPABASE_AVAILABLE,
        'storage_type': 'supabase'
    }), 200

# ==================== DEBUG ROUTES ====================

@app.route('/api/debug/test-upload', methods=['POST'])
@jwt_required()
def test_upload():
    """Test if we can upload to Supabase"""
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 500
    
    try:
        # Create a small test file in memory
        test_content = f"Test upload from Karanja Shoe Store - {datetime.now().isoformat()}".encode()
        test_filename = f"test-file-{int(datetime.now().timestamp())}.txt"
        
        # Upload using the storage API
        result = supabase.storage.from_(STORAGE_BUCKET).upload(
            path=f"test/{test_filename}",
            file=test_content,
            file_options={"content-type": "text/plain"}
        )
        
        return jsonify({
            'success': True,
            'message': 'Test upload successful',
            'path': f"test/{test_filename}"
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
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 500
    
    try:
        files = supabase.storage.from_(STORAGE_BUCKET).list()
        return jsonify({
            'success': True,
            'bucket': STORAGE_BUCKET,
            'files': files,
            'total_files': len(files)
        }), 200
    except Exception as e:
        logger.error(f"Error listing bucket: {e}")
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/debug/check-db', methods=['GET'])
@jwt_required()
def debug_check_db():
    """Check what's in the database"""
    try:
        products = get_table_data('products')
        return jsonify({
            'product_count': len(products),
            'products': products,
            'table_exists': True,
            'supabase_connected': SUPABASE_AVAILABLE
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'table_exists': False,
            'supabase_connected': SUPABASE_AVAILABLE
        }), 500

@app.route('/api/debug/test-supabase', methods=['GET'])
@jwt_required()
def test_supabase():
    """Test Supabase connection and permissions"""
    results = {}
    
    # Test 1: Check if supabase client exists
    results['client_exists'] = supabase is not None
    
    if not supabase:
        return jsonify({'error': 'Supabase client not initialized', 'results': results}), 500
    
    try:
        # Test 2: Try to list tables
        try:
            tables = supabase.table('products').select('*').limit(1).execute()
            results['can_query_products'] = True
            results['products_table_exists'] = True
        except Exception as e:
            results['can_query_products'] = False
            results['products_table_error'] = str(e)
        
        # Test 3: Try to insert a test record
        try:
            test_id = int(datetime.now().timestamp())
            test_data = {
                'id': test_id,
                'name': 'test_product',
                'description': 'test'
            }
            result = supabase.table('products').insert(test_data).execute()
            results['can_insert'] = True
            
            # Clean up test record
            supabase.table('products').delete().eq('id', test_id).execute()
        except Exception as e:
            results['can_insert'] = False
            results['insert_error'] = str(e)
        
        # Test 4: Storage access
        try:
            buckets = supabase.storage.list_buckets()
            results['can_list_buckets'] = True
            results['buckets'] = [b['name'] for b in buckets]
        except Exception as e:
            results['can_list_buckets'] = False
            results['storage_error'] = str(e)
        
        return jsonify({
            'success': True,
            'supabase_available': SUPABASE_AVAILABLE,
            'tests': results
        }), 200
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
@jwt_required()
def health_check():
    """Health check endpoint"""
    product_count = 0
    try:
        products = get_table_data('products')
        product_count = len(products)
    except:
        pass
        
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'app': 'Karanja Shoe Store',
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
        'products': product_count,
        'sales': len(get_table_data('sales')) if SUPABASE_AVAILABLE else 0,
        'storage_type': 'supabase'
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
                'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
                'status': 'online',
                'storage_type': 'supabase'
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
    logger.info("✓ KARANJA SHOE STORE - SUPABASE INTEGRATION")
    logger.info("=" * 70)
    logger.info(f"  Supabase URL: {SUPABASE_URL}")
    logger.info(f"  Storage Bucket: {STORAGE_BUCKET}")
    logger.info(f"  Connection: {'✓ Connected' if SUPABASE_AVAILABLE else '✗ Failed'}")
    logger.info("=" * 70)
    logger.info("✓ CONSTANT LOGIN CREDENTIALS:")
    logger.info(f"  Email: {CONSTANT_EMAIL}")
    logger.info(f"  Password: {CONSTANT_PASSWORD}")
    logger.info("=" * 70)
    logger.info("✓ SERVER STARTED SUCCESSFULLY")
    logger.info(f"  URL: http://0.0.0.0:{port}")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=port, debug=True)
