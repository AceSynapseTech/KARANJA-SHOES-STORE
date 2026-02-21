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
            logger.info(f"✓ Saved {len(data)} records to {table_name}")
        else:
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"✓ Saved single record to {table_name} with ID: {data.get('id', 'unknown')}")
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
        logger.info(f"✓ Deleted from {table_name}: {record_id}")
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
        
        # Get public URL
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(unique_filename)
        
        return {
            'path': unique_filename,
            'public_url': public_url,
            'proxy_url': f"/api/images/{unique_filename}"
        }, None
        
    except Exception as e:
        logger.error(f"Error uploading to Supabase: {e}")
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
            response = requests.get(public_url, timeout=10)
            if response.status_code == 200:
                resp = make_response(response.content)
                resp.headers['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=3600'
                return resp
        return send_file('static/placeholder.png')
    except Exception as e:
        logger.error(f"Error proxying image: {e}")
        return send_file('static/placeholder.png')

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

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

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
        
        # Validate file type
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if file.content_type not in allowed_types:
            return jsonify({'error': 'File type not allowed. Please upload an image.'}), 400
        
        # Upload to Supabase
        result, error = upload_to_supabase_storage(file, "products")
        
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'url': f"/api/images/{result['path']}",
            'public_url': result['public_url'],
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
        products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
        
        # Add image URLs and convert to camelCase for frontend
        for product in products:
            if product.get('image_path'):
                product['image'] = f"/api/images/{product['image_path']}"
            # Add camelCase versions
            product['buyPrice'] = product.get('buyprice', 0)
            product['minSellPrice'] = product.get('minsellprice', 0)
            product['maxSellPrice'] = product.get('maxsellprice', 0)
            product['totalStock'] = product.get('totalstock', 0)
            product['dateAdded'] = product.get('dateadded', '')
            product['lastUpdated'] = product.get('lastupdated', '')
        
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
        
        # Use lowercase column names for database
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
            product['buyprice'] = float(request.form['buyPrice'])
        if request.form.get('minSellPrice'):
            product['minsellprice'] = float(request.form['minSellPrice'])
        if request.form.get('maxSellPrice'):
            product['maxsellprice'] = float(request.form['maxSellPrice'])
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
                product['totalstock'] = total_stock
            except:
                pass
        
        # Update image
        if request.form.get('image_path'):
            # Delete old image if exists
            if product.get('image_path'):
                delete_from_supabase_storage(product['image_path'])
            product['image_path'] = request.form['image_path']
        
        product['lastupdated'] = datetime.now().isoformat()
        
        # Save to Supabase
        if save_table_data('products', product):
            # Add camelCase for response
            product['buyPrice'] = product.get('buyprice', 0)
            product['minSellPrice'] = product.get('minsellprice', 0)
            product['maxSellPrice'] = product.get('maxsellprice', 0)
            product['totalStock'] = product.get('totalstock', 0)
            product['dateAdded'] = product.get('dateadded', '')
            product['lastUpdated'] = product.get('lastupdated', '')
            
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
        products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
        
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
                'totalStock': product.get('totalstock', 0),
                'sizes': product.get('sizes', {})
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

# ==================== SALES ROUTES ====================

@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales"""
    try:
        sales = get_table_data('sales')
        # Sort by timestamp descending (newest first)
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        # Convert to camelCase for frontend
        for sale in sales:
            sale['productId'] = sale.get('productid')
            sale['productName'] = sale.get('productname')
            sale['productSKU'] = sale.get('productsku')
            sale['buyPrice'] = sale.get('buyprice', 0)
            sale['unitPrice'] = sale.get('unitprice', 0)
            sale['totalAmount'] = sale.get('totalamount', 0)
            sale['totalProfit'] = sale.get('totalprofit', 0)
            sale['customerName'] = sale.get('customername', '')
            sale['isBargain'] = sale.get('isbargain', False)
        
        logger.info(f"Returning {len(sales)} sales records")
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
        logger.info(f"Received sale data: {json.dumps(data)}")
        
        # Validate required fields
        product_id = data.get('productId')
        size = data.get('size')
        quantity = data.get('quantity')
        unit_price = data.get('unitPrice')
        
        if not all([product_id, size, quantity, unit_price]):
            missing = []
            if not product_id: missing.append('productId')
            if not size: missing.append('size')
            if not quantity: missing.append('quantity')
            if not unit_price: missing.append('unitPrice')
            return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
        
        # Get product
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        size_key = str(size)
        if size_key not in product['sizes']:
            return jsonify({'error': f'Size {size} not available for this product'}), 400
        
        current_stock = product['sizes'].get(size_key, 0)
        if current_stock < quantity:
            return jsonify({'error': f'Insufficient stock. Only {current_stock} available in size {size}'}), 400
        
        # Update stock
        product['sizes'][size_key] = current_stock - quantity
        
        # Recalculate total stock
        total_stock = 0
        for stock in product['sizes'].values():
            total_stock += stock if stock > 0 else 0
        product['totalstock'] = total_stock
        product['lastupdated'] = datetime.now().isoformat()
        
        # Save updated product
        if not save_table_data('products', product):
            logger.error("Failed to update product stock")
            return jsonify({'error': 'Failed to update product stock'}), 500
        
        # Calculate totals
        total_amount = unit_price * quantity
        total_cost = product['buyprice'] * quantity
        total_profit = total_amount - total_cost
        
        # Get optional fields
        customer_name = data.get('customerName', 'Walk-in Customer')
        notes = data.get('notes', '')
        is_bargain = data.get('isBargain', False)
        
        # Create sale record with LOWERCASE column names to match database
        sale_id = int(datetime.now().timestamp() * 1000)
        sale = {
            'id': sale_id,
            'productid': product_id,
            'productname': product['name'],
            'productsku': product.get('sku', ''),
            'category': product.get('category', ''),
            'buyprice': product['buyprice'],
            'size': size_key,
            'quantity': quantity,
            'unitprice': unit_price,
            'totalamount': total_amount,
            'totalprofit': total_profit,
            'customername': customer_name,
            'notes': notes,
            'isbargain': is_bargain,
            'timestamp': datetime.now().isoformat()
        }
        
        # Save sale
        if save_table_data('sales', sale):
            logger.info(f"✓ Sale recorded: {product['name']} - {quantity} x Size {size} @ {unit_price}")
            
            # Create notification with lowercase column names
            notification = {
                'id': int(datetime.now().timestamp() * 1000) + 1,
                'message': f'Sale: {product["name"]} ({quantity} × Size {size})',
                'type': 'success',
                'timestamp': datetime.now().isoformat(),
                'read': False
            }
            save_table_data('notifications', notification)
            
            # Prepare response with camelCase for frontend
            response_sale = {
                'id': sale_id,
                'productId': product_id,
                'productName': product['name'],
                'productSKU': product.get('sku', ''),
                'category': product.get('category', ''),
                'buyPrice': product['buyprice'],
                'size': size_key,
                'quantity': quantity,
                'unitPrice': unit_price,
                'totalAmount': total_amount,
                'totalProfit': total_profit,
                'customerName': customer_name,
                'notes': notes,
                'isBargain': is_bargain,
                'timestamp': datetime.now().isoformat()
            }
            
            return jsonify({
                'success': True,
                'sale': response_sale,
                'message': 'Sale recorded successfully'
            }), 201
        else:
            logger.error("Failed to save sale record")
            return jsonify({'error': 'Failed to save sale record'}), 500
        
    except Exception as e:
        logger.error(f"Error creating sale: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== NOTIFICATION ROUTES ====================

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    try:
        notifications = get_table_data('notifications')
        notifications.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(notifications[:50]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_notification_count():
    """Get unread notification count"""
    try:
        notifications = get_table_data('notifications')
        unread_count = len([n for n in notifications if not n.get('read', False)])
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting notification count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        notifications = get_table_data('notifications')
        for n in notifications:
            if n['id'] == notification_id:
                n['read'] = True
                save_table_data('notifications', n)
                break
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
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
        total_stock = sum([p.get('totalstock', 0) for p in products])
        total_revenue = sum([s.get('totalamount', 0) for s in sales])
        total_profit = sum([s.get('totalprofit', 0) for s in sales])
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_sales = [s for s in sales if s.get('timestamp', '').startswith(today)]
        today_revenue = sum([s.get('totalamount', 0) for s in today_sales])
        today_profit = sum([s.get('totalprofit', 0) for s in today_sales])
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

# ==================== STORAGE INFO ====================

@app.route('/api/storage/info', methods=['GET'])
@jwt_required()
def get_storage_info():
    """Get storage information"""
    return jsonify({
        'provider': 'supabase',
        'bucket': STORAGE_BUCKET,
        'connected': SUPABASE_AVAILABLE,
        'storage_type': 'supabase'
    }), 200

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    product_count = 0
    sale_count = 0
    try:
        products = get_table_data('products')
        product_count = len(products)
        sales = get_table_data('sales')
        sale_count = len(sales)
    except:
        pass
        
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
        'products': product_count,
        'sales': sale_count,
        'storage_type': 'supabase'
    }), 200

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except Exception as e:
        return jsonify({'error': 'File not found'}), 404

# ==================== INDEX ROUTE ====================

@app.route('/')
def index():
    """Serve index.html"""
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
        return jsonify({
            'message': 'Karanja Shoe Store API is running',
            'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
            'status': 'online'
        })
    except Exception as e:
        return jsonify({'error': 'Could not load index'}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}")
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
