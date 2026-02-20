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

# ==================== SUPABASE CONFIGURATION ====================
SUPABASE_URL = "https://hgcknskdvbgfiubfxdeo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhnY2tuc2tkdmJnZml1YmZ4ZGVvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MDE3MTQsImV4cCI6MjA4NzE3NzcxNH0.xuRf8pqb8DJmPtawGC8zmBQQrSo3ukEVSqe6KPyEofg"

# Buckets/Storage configuration
STORAGE_BUCKET = "product-images"

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✓ Supabase client initialized successfully")
    
    # Test connection
    try:
        # Test database access
        test_query = supabase.table('products').select('*').limit(1).execute()
        logger.info("✓ Database connection successful")
        SUPABASE_AVAILABLE = True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
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
        return False
    try:
        if isinstance(data, list):
            result = supabase.table(table_name).upsert(data).execute()
        else:
            result = supabase.table(table_name).upsert(data).execute()
        logger.info(f"✓ Saved to {table_name}")
        return True
    except Exception as e:
        logger.error(f"Error saving to {table_name}: {e}")
        logger.error(traceback.format_exc())
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
        
        # Upload to Supabase Storage
        supabase.storage.from_(STORAGE_BUCKET).upload(
            path=unique_filename,
            file=file_data,
            file_options={"content-type": file.content_type or 'image/jpeg'}
        )
        
        logger.info(f"✓ Uploaded: {unique_filename}")
        
        return {
            'path': unique_filename,
            'proxy_url': f"/api/images/{unique_filename}"
        }, None
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return None, str(e)

# ==================== IMAGE PROXY ====================

@app.route('/api/images/<path:image_path>')
def proxy_image(image_path):
    """Proxy images from Supabase storage"""
    if not supabase:
        return send_file('static/placeholder.png')
    try:
        # Get public URL
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(image_path)
        if public_url:
            response = requests.get(public_url)
            if response.status_code == 200:
                resp = make_response(response.content)
                resp.headers['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
                return resp
        return send_file('static/placeholder.png')
    except:
        return send_file('static/placeholder.png')

# ==================== AUTH ROUTES ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').upper()
    password = data.get('password', '')
    
    if email == CONSTANT_EMAIL and password == CONSTANT_PASSWORD:
        token = create_access_token(identity=CONSTANT_USER_ID)
        return jsonify({'success': True, 'token': token, 'user': {'email': CONSTANT_EMAIL}})
    return jsonify({'error': 'Invalid credentials'}), 401

# ==================== UPLOAD ROUTE ====================

@app.route('/api/supabase/upload', methods=['POST'])
@jwt_required()
def upload_to_supabase():
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 503
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        result, error = upload_to_supabase_storage(file, "products")
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'url': f"/api/images/{result['path']}",
            'path': result['path']
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    products = get_table_data('products')
    products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
    
    for p in products:
        if p.get('image_path'):
            p['image'] = f"/api/images/{p['image_path']}"
        # Add camelCase versions for frontend compatibility
        p['buyPrice'] = p.get('buyprice', 0)
        p['minSellPrice'] = p.get('minsellprice', 0)
        p['maxSellPrice'] = p.get('maxsellprice', 0)
        p['totalStock'] = p.get('totalstock', 0)
        p['dateAdded'] = p.get('dateadded', '')
        p['lastUpdated'] = p.get('lastupdated', '')
    
    return jsonify(products)

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
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
        
        # Use lowercase column names to match database
        product = {
            'id': product_id,
            'name': name.strip(),
            'sku': sku,
            'category': category,
            'color': color,
            'description': description,
            'sizes': sizes,
            'buyprice': buy_price,
            'minsellprice': min_sell,
            'maxsellprice': max_sell,
            'price': max_sell,
            'totalstock': total_stock,
            'dateadded': datetime.now().isoformat(),
            'lastupdated': datetime.now().isoformat(),
            'image_path': image_path,
            'storage': 'supabase',
            'createdby': get_jwt_identity()
        }
        
        # Log the product data for debugging
        logger.info(f"Product data: {json.dumps(product, default=str)}")
        
        # Save to Supabase
        if save_table_data('products', product):
            # Add camelCase versions for response
            product['buyPrice'] = buy_price
            product['minSellPrice'] = min_sell
            product['maxSellPrice'] = max_sell
            product['totalStock'] = total_stock
            product['dateAdded'] = product['dateadded']
            product['lastUpdated'] = product['lastupdated']
            
            if image_path:
                product['image'] = f"/api/images/{image_path}"
            
            logger.info(f"✓ Product created: {name}")
            return jsonify({'success': True, 'product': product}), 201
        else:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    try:
        supabase.table('products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PUBLIC PRODUCTS ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    products = get_table_data('products')
    products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
    
    public_products = []
    for p in products:
        public_p = {
            'id': p['id'],
            'name': p['name'],
            'sku': p.get('sku', ''),
            'category': p.get('category', ''),
            'color': p.get('color', ''),
            'price': p.get('price', 0),
            'totalStock': p.get('totalstock', 0),
            'sizes': p.get('sizes', {})
        }
        if p.get('image_path'):
            public_p['image'] = f"/api/images/{p['image_path']}"
        else:
            public_p['image'] = '/static/placeholder.png'
        public_products.append(public_p)
    
    return jsonify(public_products)

# ==================== DASHBOARD STATS ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    try:
        products = get_table_data('products')
        
        total_products = len(products)
        total_stock = sum([p.get('totalstock', 0) for p in products])
        
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
    return jsonify({
        'status': 'healthy',
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected'
    })

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    try:
        return send_from_directory('static', filename)
    except:
        return jsonify({'error': 'File not found'}), 404

# ==================== INDEX ROUTE ====================

@app.route('/')
def index():
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
        return jsonify({'message': 'API is running'})
    except:
        return jsonify({'error': 'Could not load index'}), 500

# ==================== RUN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
