from flask import Flask, request, jsonify, send_file, send_from_directory, make_response
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import json
import os
from supabase import create_client, Client
from werkzeug.utils import secure_filename
import uuid
import logging
import traceback
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB

# Create static folder for placeholder
os.makedirs('static', exist_ok=True)

# Create a simple placeholder file
placeholder_path = 'static/placeholder.png'
if not os.path.exists(placeholder_path):
    with open(placeholder_path, 'wb') as f:
        f.write(b'')

# ==================== CONSTANT LOGIN CREDENTIALS ====================
CONSTANT_EMAIL = "KARANJASHOESTORE@GMAIL.COM"
CONSTANT_PASSWORD = "0726539216"
CONSTANT_USER_ID = "1"
CONSTANT_USER_NAME = "Karanja Shoe Store"
CONSTANT_USER_ROLE = "admin"

# ==================== SUPABASE CONFIGURATION ====================
SUPABASE_URL = "https://hgcknskdvbgfiubfxdeo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhnY2tuc2tkdmJnZml1YmZ4ZGVvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MDE3MTQsImV4cCI6MjA4NzE3NzcxNH0.xuRf8pqb8DJmPtawGC8zmBQQrSo3ukEVSqe6KPyEofg"
SUPABASE_SECRET = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhnY2tuc2tkdmJnZml1YmZ4ZGVvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTYwMTcxNCwiZXhwIjoyMDg3MTc3NzE0fQ.8O_yH-h-K42yjJKTlu4ig-Lo7_3iNXt_dANQ840XpdM"

# Buckets/Storage configuration
STORAGE_BUCKET = "product-images"

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✓ Supabase client initialized successfully")
    
    # Test connection
    try:
        # Test storage access
        buckets = supabase.storage.list_buckets()
        logger.info(f"✓ Connected to Supabase. Available buckets: {[b['name'] for b in buckets]}")
        
        # Check if our bucket exists, if not create it
        bucket_exists = False
        for bucket in buckets:
            if bucket['name'] == STORAGE_BUCKET:
                bucket_exists = True
                logger.info(f"✓ Bucket '{STORAGE_BUCKET}' already exists")
                break
        
        if not bucket_exists:
            try:
                # Create the bucket
                supabase.storage.create_bucket(STORAGE_BUCKET, options={"public": False})
                logger.info(f"✓ Created bucket: {STORAGE_BUCKET}")
            except Exception as e:
                logger.warning(f"Could not create bucket: {e}")
        
        SUPABASE_AVAILABLE = True
    except Exception as e:
        logger.error(f"✗ Error accessing Supabase storage: {e}")
        SUPABASE_AVAILABLE = False
        
except Exception as e:
    logger.error(f"✗ Failed to initialize Supabase client: {e}")
    SUPABASE_AVAILABLE = False
    supabase = None

# ==================== EXTENSIONS ====================
CORS(app)
jwt = JWTManager(app)

# ==================== HELPER FUNCTIONS ====================

def get_table_data(table_name):
    """Get all data from a Supabase table"""
    if not supabase:
        logger.error(f"Supabase not available for {table_name}")
        return []
    try:
        response = supabase.table(table_name).select("*").execute()
        logger.info(f"Retrieved {len(response.data)} records from {table_name}")
        return response.data
    except Exception as e:
        logger.error(f"Error reading from {table_name}: {e}")
        return []

def save_table_data(table_name, data):
    """Save data to Supabase table"""
    if not supabase:
        logger.error(f"Supabase not available for saving to {table_name}")
        return False
    try:
        if isinstance(data, list):
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"Saved {len(data)} records to {table_name}")
        else:
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"Saved single record to {table_name} with ID: {data.get('id', 'unknown')}")
        return True
    except Exception as e:
        logger.error(f"Error saving to {table_name}: {e}")
        logger.error(traceback.format_exc())
        return False

def delete_table_data(table_name, record_id):
    """Delete data from Supabase table"""
    if not supabase:
        return False
    try:
        supabase.table(table_name).delete().eq("id", record_id).execute()
        logger.info(f"Deleted from {table_name}: {record_id}")
        return True
    except Exception as e:
        logger.error(f"Error deleting from {table_name}: {e}")
        return False

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
        content_type = file.content_type or 'image/jpeg'
        
        logger.info(f"Uploading to Supabase: {unique_filename} ({len(file_data)} bytes)")
        
        # Upload to Supabase Storage
        supabase.storage.from_(STORAGE_BUCKET).upload(
            path=unique_filename,
            file=file_data,
            file_options={"content-type": content_type}
        )
        
        logger.info(f"✓ Successfully uploaded to Supabase: {unique_filename}")
        
        # Generate signed URL for private bucket
        signed_url = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(unique_filename, 3600)
        
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
        logger.info(f"✓ Deleted from Supabase: {path}")
        return True
    except Exception as e:
        logger.error(f"Error deleting from Supabase: {e}")
        return False

# ==================== IMAGE PROXY ROUTE ====================

@app.route('/api/images/<path:image_path>')
def proxy_image(image_path):
    """Proxy images from Supabase storage"""
    if not supabase:
        logger.warning("Supabase not available, serving placeholder")
        return send_file('static/placeholder.png')
    
    try:
        # Get signed URL
        signed_url = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(image_path, 3600)
        
        if not signed_url:
            return send_file('static/placeholder.png')
        
        # Fetch the image from Supabase
        response = requests.get(signed_url['signedURL'])
        
        if response.status_code == 200:
            resp = make_response(response.content)
            resp.headers['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
            resp.headers['Cache-Control'] = 'public, max-age=3600'
            return resp
        else:
            return send_file('static/placeholder.png')
            
    except Exception as e:
        logger.error(f"Error proxying image {image_path}: {e}")
        return send_file('static/placeholder.png')

# ==================== TEST ROUTE ====================

@app.route('/api/test', methods=['GET'])
def test():
    """Test endpoint to verify app is running"""
    return jsonify({
        'status': 'ok',
        'message': 'Flask app is running',
        'supabase_connected': SUPABASE_AVAILABLE
    })

# ==================== DIAGNOSTIC ROUTE ====================

@app.route('/api/diagnose', methods=['GET'])
def diagnose():
    """Diagnose Supabase connection"""
    results = {
        'supabase_configured': bool(SUPABASE_URL and SUPABASE_KEY),
        'supabase_client_created': supabase is not None,
        'supabase_available': SUPABASE_AVAILABLE
    }
    
    if supabase:
        try:
            # Test database
            test_query = supabase.table('products').select('*').limit(1).execute()
            results['database_accessible'] = True
        except Exception as e:
            results['database_accessible'] = False
            results['database_error'] = str(e)
        
        try:
            # Test storage
            buckets = supabase.storage.list_buckets()
            results['storage_accessible'] = True
            results['buckets'] = [b['name'] for b in buckets]
        except Exception as e:
            results['storage_accessible'] = False
            results['storage_error'] = str(e)
    
    return jsonify(results)

# ==================== AUTH ROUTES ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user with constant credentials"""
    try:
        data = request.get_json()
        email = data.get('email', '').upper()
        password = data.get('password', '')
        
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
    """Get current authenticated user"""
    return jsonify({
        'id': CONSTANT_USER_ID,
        'email': CONSTANT_EMAIL,
        'name': CONSTANT_USER_NAME,
        'role': CONSTANT_USER_ROLE
    }), 200

# ==================== UPLOAD ROUTE ====================

@app.route('/api/supabase/upload', methods=['POST'])
@jwt_required()
def upload_to_supabase():
    """Upload image to Supabase Storage"""
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 503
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Upload to Supabase
        result, error = upload_to_supabase_storage(file, "products")
        
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'url': f"/api/images/{result['path']}",
            'proxy_url': f"/api/images/{result['path']}",
            'path': result['path']
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Add image URLs
        for product in products:
            if product.get('image_path'):
                product['image'] = f"/api/images/{product['image_path']}"
        
        return jsonify(products), 200
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
    try:
        # Get form data
        name = request.form.get('name')
        if not name:
            return jsonify({'error': 'Product name required'}), 400
        
        sku = request.form.get('sku', f"KS-{uuid.uuid4().hex[:8].upper()}")
        category = request.form.get('category', 'Uncategorized')
        color = request.form.get('color', '')
        description = request.form.get('description', '')
        
        # Parse sizes
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
        except:
            sizes = {}
        
        # Get prices
        buy_price = float(request.form.get('buyPrice', 0))
        min_sell = float(request.form.get('minSellPrice', 0))
        max_sell = float(request.form.get('maxSellPrice', 0))
        image_path = request.form.get('image_path')
        
        # Calculate total stock
        total_stock = 0
        for stock in sizes.values():
            try:
                total_stock += int(stock) if stock and int(stock) > 0 else 0
            except:
                pass
        
        product_id = int(datetime.now().timestamp() * 1000)
        
        product = {
            'id': product_id,
            'name': name.strip(),
            'sku': sku,
            'category': category,
            'color': color,
            'description': description,
            'sizes': sizes,
            'buyPrice': buy_price,
            'minSellPrice': min_sell,
            'maxSellPrice': max_sell,
            'price': max_sell,
            'totalStock': total_stock,
            'dateAdded': datetime.now().isoformat(),
            'lastUpdated': datetime.now().isoformat(),
            'image_path': image_path
        }
        
        # Save to Supabase
        if save_table_data('products', product):
            if image_path:
                product['image'] = f"/api/images/{image_path}"
            
            logger.info(f"✓ Product created: {name} (ID: {product_id})")
            return jsonify({'success': True, 'product': product}), 201
        else:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
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
        
        # Update fields
        if request.form.get('name'):
            product['name'] = request.form['name'].strip()
        if request.form.get('category'):
            product['category'] = request.form['category']
        if request.form.get('color'):
            product['color'] = request.form['color']
        if request.form.get('description'):
            product['description'] = request.form['description']
        if request.form.get('buyPrice'):
            product['buyPrice'] = float(request.form['buyPrice'])
        if request.form.get('minSellPrice'):
            product['minSellPrice'] = float(request.form['minSellPrice'])
        if request.form.get('maxSellPrice'):
            product['maxSellPrice'] = float(request.form['maxSellPrice'])
            product['price'] = float(request.form['maxSellPrice'])
        
        # Update sizes
        if request.form.get('sizes'):
            try:
                sizes = json.loads(request.form['sizes'])
                product['sizes'] = sizes
                
                total_stock = 0
                for stock in sizes.values():
                    try:
                        total_stock += int(stock) if stock and int(stock) > 0 else 0
                    except:
                        pass
                product['totalStock'] = total_stock
            except:
                pass
        
        # Update image
        if request.form.get('image_path'):
            # Delete old image if exists
            if product.get('image_path'):
                delete_from_supabase_storage(product['image_path'])
            product['image_path'] = request.form['image_path']
        
        product['lastUpdated'] = datetime.now().isoformat()
        
        # Save to Supabase
        if save_table_data('products', product):
            if product.get('image_path'):
                product['image'] = f"/api/images/{product['image_path']}"
            return jsonify({'success': True, 'product': product}), 200
        else:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
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
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Delete image from storage if exists
        if product.get('image_path'):
            delete_from_supabase_storage(product['image_path'])
        
        # Delete from database
        if delete_table_data('products', product_id):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to delete from Supabase'}), 500
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PUBLIC PRODUCTS ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint for products (no auth required)"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateAdded', ''), reverse=True)
        
        # Remove sensitive data
        public_products = []
        for product in products:
            public_product = {
                'id': product['id'],
                'name': product['name'],
                'sku': product.get('sku', ''),
                'category': product.get('category', ''),
                'color': product.get('color', ''),
                'description': product.get('description', ''),
                'price': product.get('price', 0),
                'totalStock': product.get('totalStock', 0),
                'sizes': product.get('sizes', {}),
                'dateAdded': product.get('dateAdded', '')
            }
            
            if product.get('image_path'):
                public_product['image'] = f"/api/images/{product['image_path']}"
                public_product['imageUrl'] = f"/api/images/{product['image_path']}"
            else:
                public_product['image'] = '/static/placeholder.png'
            
            public_products.append(public_product)
        
        return jsonify(public_products), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

# ==================== DASHBOARD STATS ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        products = get_table_data('products')
        
        total_products = len(products)
        total_stock = sum([p.get('totalStock', 0) for p in products])
        
        return jsonify({
            'totalProducts': total_products,
            'totalStock': total_stock,
            'totalRevenue': 0,
            'totalProfit': 0,
            'todayRevenue': 0,
            'todayProfit': 0,
            'todayItems': 0,
            'salesCount': 0,
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

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
        'storage_type': 'supabase'
    }), 200

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except Exception as e:
        return jsonify({'error': 'Static file not found'}), 404

# ==================== INDEX ROUTE ====================

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
                'status': 'online'
            }), 200
    except Exception as e:
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
    except:
        pass
    
    return jsonify({'error': 'Page not found'}), 404

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return index()

@app.errorhandler(500)
def internal_server_error(e):
    logger.error(f"Internal server error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info("KARANJA SHOE STORE - SUPABASE")
    logger.info("=" * 60)
    logger.info(f"Supabase URL: {SUPABASE_URL}")
    logger.info(f"Storage Bucket: {STORAGE_BUCKET}")
    logger.info(f"Connection: {'✓ Connected' if SUPABASE_AVAILABLE else '✗ Failed'}")
    logger.info("=" * 60)
    logger.info(f"Server starting on port {port}")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=True)
