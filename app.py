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
import random
import string

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB max file size
app.config['UPLOAD_FOLDER'] = '/tmp'  # Render uses ephemeral storage

# ==================== BACKBLAZE B2 CONFIGURATION ====================
B2_CONFIG = {
    'ENDPOINT': 's3.eu-central-003.backblazeb2.com',
    'BUCKET_NAME': 'karanja-shoe-store',
    'BUCKET_ID': '9240b308551f401795cd0d15',
    'ACCESS_KEY_ID': '20385f075dd5',
    'SECRET_ACCESS_KEY': 'K003u7BZcFjrpmN/s5RQQNwbhULv8vc',
    'REGION': 'eu-central-003',
    'CDN_URL': 'https://f005.backblazeb2.com/file/karanja-shoe-store',
    'CREATED_DATE': 'February 9, 2026'
}

# Initialize Backblaze B2 client
b2_client = boto3.client(
    's3',
    endpoint_url=f'https://{B2_CONFIG["ENDPOINT"]}',
    aws_access_key_id=B2_CONFIG['ACCESS_KEY_ID'],
    aws_secret_access_key=B2_CONFIG['SECRET_ACCESS_KEY'],
    config=Config(signature_version='s3v4', region_name=B2_CONFIG['REGION'])
)

# ==================== EXTENSIONS ====================
CORS(app, resources={
    r"/api/*": {
        "origins": ["http://localhost:5000", "https://*.onrender.com", "https://*.github.io"],
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
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
        self.settings = {}
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
                    self.settings = data.get('settings', {})
                    self.monthly_category_sales = data.get('monthly_category_sales', {})
                    self.daily_statements = data.get('daily_statements', [])
                    self.budget_plans = data.get('budget_plans', [])
                    self.sale_statements = data.get('sale_statements', [])
                    self.b2_images = data.get('b2_images', [])
                    self.users = data.get('users', [])
        except Exception as e:
            print(f"Error loading data: {e}")
        
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
        except Exception as e:
            print(f"Error saving data: {e}")

data_store = DataStore()

# ==================== AUTHENTICATION DECORATOR ====================
def admin_required(f):
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        user = next((u for u in data_store.users if str(u['id']) == current_user_id), None)
        if not user or user.get('role') != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==================== AUTHENTICATION ROUTES ====================
@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user and return JWT token"""
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

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user"""
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

@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout user"""
    return jsonify({'success': True}), 200

# ==================== BACKBLAZE B2 ROUTES ====================
@app.route('/api/b2/upload', methods=['POST'])
@jwt_required()
@admin_required
def upload_to_b2():
    """Upload image to Backblaze B2"""
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({'error': 'No image selected'}), 400
    
    if file.content_length > CONFIG['MAX_IMAGE_SIZE']:
        return jsonify({'error': 'Image size exceeds 20MB'}), 400
    
    try:
        # Generate unique filename
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        unique_filename = f"{timestamp}_{safe_filename}"
        s3_key = f"products/{unique_filename}"
        
        # Upload to B2
        file.seek(0)
        b2_client.upload_fileobj(
            file,
            B2_CONFIG['BUCKET_NAME'],
            s3_key,
            ExtraArgs={
                'ACL': 'public-read',
                'ContentType': file.content_type
            }
        )
        
        # Generate public URL
        public_url = f"{B2_CONFIG['CDN_URL']}/{s3_key}"
        
        # Store record
        image_record = {
            'id': str(uuid.uuid4()),
            'url': public_url,
            'fileName': unique_filename,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'size': file.content_length,
            'type': file.content_type,
            'uploadedAt': datetime.now().isoformat()
        }
        data_store.b2_images.append(image_record)
        data_store.save_data()
        
        return jsonify({
            'success': True,
            'url': public_url,
            'fileName': unique_filename,
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'cdnUrl': B2_CONFIG['CDN_URL']
        }), 200
        
    except ClientError as e:
        return jsonify({'error': f'B2 upload failed: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2/bucket-info', methods=['GET'])
@jwt_required()
def get_b2_bucket_info():
    """Get Backblaze B2 bucket information"""
    return jsonify({
        'bucketId': B2_CONFIG['BUCKET_ID'],
        'bucketName': B2_CONFIG['BUCKET_NAME'],
        'endpoint': B2_CONFIG['ENDPOINT'],
        'region': B2_CONFIG['REGION'],
        'created': B2_CONFIG['CREATED_DATE'],
        'cdnUrl': B2_CONFIG['CDN_URL'],
        'files': len(data_store.b2_images)
    }), 200

@app.route('/api/b2/images', methods=['GET'])
@jwt_required()
def get_b2_images():
    """Get all B2 images"""
    return jsonify(data_store.b2_images), 200

# ==================== PRODUCT ROUTES ====================
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with optional filtering"""
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
    
    return jsonify(products), 200

@app.route('/api/products/<int:product_id>', methods=['GET'])
@jwt_required()
def get_product(product_id):
    """Get single product by ID"""
    product = next((p for p in data_store.products if p['id'] == product_id), None)
    
    if product:
        return jsonify(product), 200
    
    return jsonify({'error': 'Product not found'}), 404

@app.route('/api/products', methods=['POST'])
@jwt_required()
@admin_required
def create_product():
    """Create new product"""
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['name', 'category', 'buyPrice', 'minSellPrice', 'maxSellPrice', 'sizes']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # Calculate total stock
    total_stock = 0
    if data['sizes']:
        total_stock = sum([int(v) for v in data['sizes'].values() if v > 0])
    
    # Create product
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
        'image': data.get('image', 'https://via.placeholder.com/300x300?text=Shoe+Image'),
        'totalStock': total_stock,
        'dateAdded': datetime.now().isoformat(),
        'lastUpdated': datetime.now().isoformat(),
        'storage': data.get('storage', {
            'type': 'backblaze-b2',
            'bucket': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'uploadedAt': datetime.now().isoformat()
        })
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
    
    return jsonify(product), 201

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
@admin_required
def update_product(product_id):
    """Update existing product"""
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
    
    # Recalculate total stock
    if 'sizes' in data:
        total_stock = 0
        for stock in data['sizes'].values():
            total_stock += int(stock) if stock > 0 else 0
        product['totalStock'] = total_stock
    
    product['lastUpdated'] = datetime.now().isoformat()
    
    data_store.save_data()
    
    return jsonify(product), 200

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def delete_product(product_id):
    """Delete product"""
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
    
    return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200

@app.route('/api/products/categories', methods=['GET'])
@jwt_required()
def get_categories():
    """Get all unique product categories"""
    categories = list(set([p.get('category') for p in data_store.products if p.get('category')]))
    categories.sort()
    return jsonify(categories), 200

@app.route('/api/products/colors', methods=['GET'])
@jwt_required()
def get_colors():
    """Get all unique product colors"""
    colors = list(set([p.get('color') for p in data_store.products if p.get('color')]))
    colors.sort()
    return jsonify(colors), 200

@app.route('/api/products/sizes', methods=['GET'])
@jwt_required()
def get_sizes():
    """Get size range"""
    return jsonify(list(range(CONFIG['SIZE_RANGE']['MIN'], CONFIG['SIZE_RANGE']['MAX'] + 1))), 200

# ==================== SALES ROUTES ====================
@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales with optional time period filtering"""
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

@app.route('/api/sales', methods=['POST'])
@jwt_required()
@admin_required
def create_sale():
    """Record new sale"""
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
    if product['sizes'].get(str(data['size']), 0) < data['quantity']:
        return jsonify({'error': 'Insufficient stock'}), 400
    
    # Update product stock
    product['sizes'][str(data['size'])] -= data['quantity']
    if product['sizes'][str(data['size'])] < 0:
        product['sizes'][str(data['size'])] = 0
    
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
    
    return jsonify({
        'sale': sale,
        'statement': statement
    }), 201

@app.route('/api/sales/statements', methods=['GET'])
@jwt_required()
def get_sale_statements():
    """Get all sale statements"""
    return jsonify(data_store.sale_statements), 200

@app.route('/api/sales/statements/<sale_id>', methods=['GET'])
@jwt_required()
def get_sale_statement(sale_id):
    """Get specific sale statement"""
    statement = next((s for s in data_store.sale_statements if s['saleId'] == int(sale_id)), None)
    
    if statement:
        return jsonify(statement), 200
    
    return jsonify({'error': 'Statement not found'}), 404

@app.route('/api/sales/statements/<int:sale_id>/download', methods=['GET'])
@jwt_required()
def download_sale_statement(sale_id):
    """Download sale statement as text file"""
    statement = next((s for s in data_store.sale_statements if s['saleId'] == sale_id), None)
    
    if not statement:
        return jsonify({'error': 'Statement not found'}), 404
    
    content = f"""
SALE STATEMENT
================
Statement ID: {statement['id']}
Sale ID: {statement['saleId']}
Date: {statement['timestamp']}

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
Images stored on: Backblaze B2 (s3.eu-central-003.backblazeb2.com)
    """
    
    return send_file(
        io.BytesIO(content.encode('utf-8')),
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"sale_statement_{statement['id']}.txt"
    )

# ==================== DASHBOARD STATS ROUTES ====================
@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics for a specific time period"""
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
    for i in range(days_to_show - 1, -1, -7):  # Sample every 7 days
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

@app.route('/api/dashboard/daily-statement', methods=['POST'])
@jwt_required()
@admin_required
def generate_daily_statement():
    """Generate daily sales statement"""
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
    
    return jsonify(statement), 201

@app.route('/api/dashboard/daily-statements', methods=['GET'])
@jwt_required()
def get_daily_statements():
    """Get all daily statements"""
    return jsonify(data_store.daily_statements), 200

@app.route('/api/dashboard/daily-statement/download', methods=['GET'])
@jwt_required()
def download_daily_statement():
    """Download daily statement as CSV"""
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
    writer.writerow([f'Images stored on: Backblaze B2 ({B2_CONFIG["ENDPOINT"]})'])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f"sales_statement_{statement['date'][:10]}.csv"
    )

# ==================== FINANCE ROUTES ====================
@app.route('/api/finance/overview', methods=['GET'])
@jwt_required()
def get_finance_overview():
    """Get financial overview"""
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
    else:
        # Get all time
        pass
    
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

# ==================== STOCK ANALYSIS ROUTES ====================
@app.route('/api/stock/analysis', methods=['GET'])
@jwt_required()
def get_stock_analysis():
    """Get stock analysis and category rankings"""
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

@app.route('/api/stock/alerts', methods=['GET'])
@jwt_required()
def get_stock_alerts():
    """Get stock alerts"""
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
    
    return jsonify(alerts), 200

@app.route('/api/stock/budget-plan', methods=['GET'])
@jwt_required()
def get_budget_plan():
    """Get bi-weekly budget plan"""
    two_weeks_ago = (datetime.now() - timedelta(days=14)).isoformat()
    
    recent_sales = [s for s in data_store.sales if s.get('timestamp', '') >= two_weeks_ago]
    
    total_revenue = sum([s['totalAmount'] for s in recent_sales])
    total_profit = sum([s['totalProfit'] for s in recent_sales])
    avg_daily_revenue = total_revenue / 14 if recent_sales else 0
    profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Calculate budget based on profit
    weekly_budget = max(total_profit * 0.3, 1000)
    
    # Get category performance
    rankings = get_stock_analysis().json
    
    high_demand = [c for c in rankings if 'High' in c.get('demandLevel', '')][:3]
    low_demand = [c for c in rankings if 'Low' in c.get('demandLevel', '')][:3]
    
    # Restock recommendations
    restock_recommendations = []
    for product in data_store.products:
        product_sales = [s for s in recent_sales if s['productId'] == product['id']]
        sales_count = sum([s['quantity'] for s in product_sales])
        
        if product.get('dateAdded'):
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
        'budgetAllocation': budget_allocation
    }), 200

# ==================== BUSINESS PLAN ROUTES ====================
@app.route('/api/business-plan', methods=['GET'])
@jwt_required()
def get_business_plan():
    """Get business plan calculations"""
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

# ==================== NOTIFICATION ROUTES ====================
@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    unread_only = request.args.get('unread', '').lower() == 'true'
    
    notifications = data_store.notifications
    
    if unread_only:
        notifications = [n for n in notifications if not n.get('read', False)]
    
    return jsonify(notifications[:50]), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    notification = next((n for n in data_store.notifications if n['id'] == notification_id), None)
    
    if notification:
        notification['read'] = True
        data_store.save_data()
        return jsonify({'success': True}), 200
    
    return jsonify({'error': 'Notification not found'}), 404

@app.route('/api/notifications/read-all', methods=['PUT'])
@jwt_required()
def mark_all_notifications_read():
    """Mark all notifications as read"""
    for notification in data_store.notifications:
        notification['read'] = True
    
    data_store.save_data()
    
    return jsonify({'success': True}), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_unread_notification_count():
    """Get unread notification count"""
    unread_count = len([n for n in data_store.notifications if not n.get('read', False)])
    
    return jsonify({'count': unread_count}), 200

# ==================== SETTINGS ROUTES ====================
@app.route('/api/settings', methods=['GET'])
@jwt_required()
def get_settings():
    """Get application settings"""
    return jsonify(data_store.settings), 200

@app.route('/api/settings', methods=['PUT'])
@jwt_required()
@admin_required
def update_settings():
    """Update application settings"""
    data = request.get_json()
    
    data_store.settings.update(data)
    data_store.save_data()
    
    return jsonify(data_store.settings), 200

# ==================== HEALTH CHECK ====================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'app': CONFIG['APP_NAME'],
        'created': B2_CONFIG['CREATED_DATE'],
        'b2_bucket': B2_CONFIG['BUCKET_NAME'],
        'b2_endpoint': B2_CONFIG['ENDPOINT'],
        'products': len(data_store.products),
        'sales': len(data_store.sales)
    }), 200

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 20MB'}), 413

# ==================== CATCH-ALL ROUTE FOR SPA ====================
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API routes"""
    try:
        with open('index.html', 'r') as f:
            return render_template_string(f.read())
    except Exception as e:
        return jsonify({'error': 'index.html not found', 'message': str(e)}), 404

# ==================== INITIALIZE DATA ====================
def init_data():
    """Initialize sample data if no products exist"""
    if len(data_store.products) == 0:
        # Create sample products
        sample_sizes = {}
        for i in range(CONFIG['SIZE_RANGE']['MIN'], CONFIG['SIZE_RANGE']['MAX'] + 1):
            if i % 5 == 0:  # Every 5th size
                sample_sizes[str(i)] = random.randint(5, 15)
        
        sample_products = [
            {
                'name': 'Leather Formal Shoes',
                'sku': 'KS-001',
                'category': 'Official Shoes',
                'color': 'Black',
                'sizes': sample_sizes.copy(),
                'buyPrice': 1500,
                'minSellPrice': 2200,
                'maxSellPrice': 2800,
                'description': 'Premium leather formal shoes, perfect for office wear',
                'image': 'https://f005.backblazeb2.com/file/karanja-shoe-store/products/sample_leather_shoes.jpg',
                'totalStock': sum(sample_sizes.values()),
                'dateAdded': datetime.now().isoformat(),
                'lastUpdated': datetime.now().isoformat(),
                'storage': {
                    'type': 'backblaze-b2',
                    'bucket': B2_CONFIG['BUCKET_ID'],
                    'bucketName': B2_CONFIG['BUCKET_NAME'],
                    'endpoint': B2_CONFIG['ENDPOINT'],
                    'uploadedAt': datetime.now().isoformat()
                }
            },
            {
                'name': 'Running Sports Shoes',
                'sku': 'KS-002',
                'category': 'Sports Shoes',
                'color': 'White/Blue',
                'sizes': sample_sizes.copy(),
                'buyPrice': 1200,
                'minSellPrice': 1800,
                'maxSellPrice': 2500,
                'description': 'Comfortable running shoes with cushioned sole',
                'image': 'https://f005.backblazeb2.com/file/karanja-shoe-store/products/sample_sports_shoes.jpg',
                'totalStock': sum(sample_sizes.values()),
                'dateAdded': datetime.now().isoformat(),
                'lastUpdated': datetime.now().isoformat(),
                'storage': {
                    'type': 'backblaze-b2',
                    'bucket': B2_CONFIG['BUCKET_ID'],
                    'bucketName': B2_CONFIG['BUCKET_NAME'],
                    'endpoint': B2_CONFIG['ENDPOINT'],
                    'uploadedAt': datetime.now().isoformat()
                }
            }
        ]
        
        for product in sample_products:
            product['id'] = int(datetime.now().timestamp() * 1000) + random.randint(1, 1000)
            data_store.products.append(product)
        
        data_store.save_data()
        
        # Add welcome notification
        notification = {
            'id': int(datetime.now().timestamp() * 1000),
            'message': 'Welcome to Karanja Shoe Store! Sample products have been created.',
            'type': 'info',
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        data_store.notifications.insert(0, notification)
        data_store.save_data()

# Initialize sample data
init_data()

# ==================== RUN APPLICATION ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
