import os
import json
import uuid
import datetime
from flask import Flask, render_template, request, jsonify, send_file, make_response
from flask_cors import CORS
from werkzeug.utils import secure_filename
from functools import wraps
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import io
import csv
import requests

# ==================== CONFIGURATION ====================
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Backblaze B2 Configuration
    B2_ENDPOINT = 's3.eu-central-003.backblazeb2.com'
    B2_BUCKET_NAME = 'karanja-shoe-store'
    B2_BUCKET_ID = '9240b308551f401795cd0d15'
    B2_REGION = 'eu-central-003'
    B2_CDN_URL = 'https://f005.backblazeb2.com/file/karanja-shoe-store'
    B2_ACCESS_KEY_ID = os.environ.get('B2_ACCESS_KEY_ID', '20385f075dd5')
    B2_SECRET_ACCESS_KEY = os.environ.get('B2_SECRET_ACCESS_KEY', '')
    
    MAX_IMAGE_SIZE = 20 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    CURRENCY = 'KES'
    LOW_STOCK_THRESHOLD = 3
    OLD_STOCK_DAYS = 30
    
    TITHE_PERCENTAGE = 10
    SAVINGS_PERCENTAGE = 20
    RESTOCK_PERCENTAGE = 30
    DEDUCTIONS_PERCENTAGE = 15
    PERSONAL_INCOME_PERCENTAGE = 25

# ==================== INITIALIZE FLASK ====================
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
CORS(app)

# ==================== HELPER FUNCTION FOR JSON SERIALIZATION ====================
def json_serializer(obj):
    """Convert datetime objects to ISO format strings for JSON serialization"""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

# ==================== BACKBLAZE B2 CLIENT ====================
class BackblazeB2Client:
    def __init__(self):
        self.access_key_id = Config.B2_ACCESS_KEY_ID
        self.secret_access_key = Config.B2_SECRET_ACCESS_KEY
        self.endpoint = Config.B2_ENDPOINT
        self.bucket_name = Config.B2_BUCKET_NAME
        self.bucket_id = Config.B2_BUCKET_ID
        self.region = Config.B2_REGION
        self.cdn_url = Config.B2_CDN_URL
        self.client = None
        self.initialized = False
        
        if self.secret_access_key:
            self.initialize_client()
    
    def initialize_client(self):
        try:
            session = boto3.session.Session()
            self.client = session.client(
                's3',
                endpoint_url=f'https://{self.endpoint}',
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=Config(signature_version='s3v4', region_name=self.region)
            )
            self.initialized = True
            print("✅ Backblaze B2 client initialized")
            return True
        except Exception as e:
            print(f"❌ B2 init failed: {e}")
            return False
    
    def is_initialized(self):
        return self.initialized and self.client is not None and self.secret_access_key
    
    def upload_file(self, file_data, filename, content_type):
        if not self.is_initialized():
            timestamp = int(datetime.datetime.now().timestamp())
            safe_filename = secure_filename(filename)
            unique_filename = f"{timestamp}_{safe_filename}"
            public_url = f"{self.cdn_url}/products/{unique_filename}"
            return {
                'success': True,
                'url': public_url,
                'filename': unique_filename,
                'bucket': self.bucket_name,
                'demo_mode': True
            }
        
        try:
            timestamp = int(datetime.datetime.now().timestamp())
            safe_filename = secure_filename(filename)
            unique_filename = f"product_{timestamp}_{safe_filename}"
            
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=f"products/{unique_filename}",
                Body=file_data,
                ContentType=content_type,
                ACL='public-read'
            )
            
            public_url = f"{self.cdn_url}/products/{unique_filename}"
            
            return {
                'success': True,
                'url': public_url,
                'filename': unique_filename,
                'bucket': self.bucket_name,
                'bucket_id': self.bucket_id,
                'endpoint': self.endpoint,
                'demo_mode': False
            }
        except ClientError as e:
            print(f"B2 Upload Error: {e}")
            return {'success': False, 'error': str(e)}
    
    def get_bucket_info(self):
        return {
            'bucket_id': self.bucket_id,
            'bucket_name': self.bucket_name,
            'endpoint': self.endpoint,
            'region': self.region,
            'cdn_url': self.cdn_url,
            'created': 'February 9, 2026',
            'type': 'Private with public read',
            'file_lifecycle': 'Keep all versions',
            'encryption': 'Disabled',
            'cors': 'Enabled'
        }

b2_client = BackblazeB2Client()

# ==================== DATA STORAGE ====================
class DataStore:
    def __init__(self):
        self.data_dir = 'data'
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.products_file = os.path.join(self.data_dir, 'products.json')
        self.sales_file = os.path.join(self.data_dir, 'sales.json')
        self.notifications_file = os.path.join(self.data_dir, 'notifications.json')
        self.settings_file = os.path.join(self.data_dir, 'settings.json')
        self.b2_images_file = os.path.join(self.data_dir, 'b2_images.json')
        self.sale_statements_file = os.path.join(self.data_dir, 'sale_statements.json')
        self.category_sales_file = os.path.join(self.data_dir, 'category_sales.json')
        
        self._init_files()
    
    def _init_files(self):
        for file in [self.products_file, self.sales_file, self.notifications_file, 
                     self.settings_file, self.b2_images_file, self.sale_statements_file,
                     self.category_sales_file]:
            if not os.path.exists(file):
                with open(file, 'w') as f:
                    json.dump([], f)
        
        if os.path.getsize(self.settings_file) == 0:
            with open(self.settings_file, 'w') as f:
                json.dump({
                    'currency': Config.CURRENCY,
                    'low_stock_threshold': Config.LOW_STOCK_THRESHOLD,
                    'old_stock_days': Config.OLD_STOCK_DAYS,
                    'b2_bucket': Config.B2_BUCKET_ID,
                    'b2_endpoint': Config.B2_ENDPOINT
                }, f)
    
    def _read_json(self, filepath):
        try:
            with open(filepath, 'r') as f:
                content = f.read().strip()
                return json.loads(content) if content else []
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _write_json(self, filepath, data):
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
    
    def get_products(self):
        return self._read_json(self.products_file)
    
    def save_products(self, products):
        self._write_json(self.products_file, products)
    
    def get_sales(self):
        return self._read_json(self.sales_file)
    
    def save_sales(self, sales):
        self._write_json(self.sales_file, sales)
    
    def get_notifications(self):
        return self._read_json(self.notifications_file)
    
    def save_notifications(self, notifications):
        self._write_json(self.notifications_file, notifications)
    
    def get_settings(self):
        data = self._read_json(self.settings_file)
        return data if isinstance(data, dict) else {}
    
    def save_settings(self, settings):
        self._write_json(self.settings_file, settings)
    
    def get_b2_images(self):
        return self._read_json(self.b2_images_file)
    
    def save_b2_images(self, images):
        self._write_json(self.b2_images_file, images)
    
    def get_sale_statements(self):
        return self._read_json(self.sale_statements_file)
    
    def save_sale_statements(self, statements):
        self._write_json(self.sale_statements_file, statements)
    
    def get_category_sales(self):
        category_data = self._read_json(self.category_sales_file)
        if isinstance(category_data, list):
            return {}
        return category_data if isinstance(category_data, dict) else {}
    
    def save_category_sales(self, data):
        self._write_json(self.category_sales_file, data)

data_store = DataStore()

# ==================== AUTHENTICATION ====================
def authenticate(email, password):
    if email and password and '@' in email and len(password) >= 6:
        return {
            'success': True,
            'user': {
                'email': email,
                'name': email.split('@')[0].replace('.', ' ').replace('-', ' ').title(),
                'role': 'admin',
                'login_time': datetime.datetime.now().isoformat()
            }
        }
    return {'success': False, 'error': 'Invalid credentials'}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authentication required'}), 401
        token = auth_header.replace('Bearer ', '')
        if token != app.secret_key:
            return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ==================== UTILITY FUNCTIONS ====================
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def format_currency(amount):
    return f"{Config.CURRENCY} {float(amount):,.2f}"

def calculate_total_stock(product):
    total = 0
    if product and product.get('sizes'):
        for size, stock in product['sizes'].items():
            total += int(stock) if stock else 0
    return total

def generate_sku():
    return f"KS-{str(uuid.uuid4())[:8].upper()}"

def add_notification(message, type='info'):
    notification = {
        'id': int(datetime.datetime.now().timestamp() * 1000),
        'message': message,
        'type': type,
        'timestamp': datetime.datetime.now().isoformat(),
        'read': False
    }
    notifications = data_store.get_notifications()
    notifications.insert(0, notification)
    if len(notifications) > 100:
        notifications = notifications[:100]
    data_store.save_notifications(notifications)
    return notification

def record_monthly_category_sale(category, amount, quantity, profit):
    now = datetime.datetime.now()
    month_key = now.strftime('%Y-%m')
    category_sales = data_store.get_category_sales()
    
    if month_key not in category_sales:
        category_sales[month_key] = {}
    if category not in category_sales[month_key]:
        category_sales[month_key][category] = {
            'revenue': 0,
            'quantity': 0,
            'profit': 0
        }
    
    category_sales[month_key][category]['revenue'] += amount
    category_sales[month_key][category]['quantity'] += quantity
    category_sales[month_key][category]['profit'] += profit
    
    data_store.save_category_sales(category_sales)

# ==================== ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    result = authenticate(email, password)
    if result['success']:
        return jsonify({
            'success': True,
            'token': app.secret_key,
            'user': result['user']
        })
    return jsonify(result), 401

@app.route('/api/auth/verify', methods=['GET'])
@login_required
def verify_token():
    return jsonify({'valid': True})

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    products = data_store.get_products()
    for product in products:
        product['totalStock'] = calculate_total_stock(product)
    return jsonify(products)

@app.route('/api/products/<int:product_id>', methods=['GET'])
@login_required
def get_product(product_id):
    products = data_store.get_products()
    product = next((p for p in products if p['id'] == product_id), None)
    if product:
        product['totalStock'] = calculate_total_stock(product)
        return jsonify(product)
    return jsonify({'error': 'Product not found'}), 404

@app.route('/api/products', methods=['POST'])
@login_required
def create_product():
    try:
        data = request.json
        required_fields = ['name', 'category', 'color', 'buyPrice', 'minSellPrice', 'maxSellPrice', 'sizes']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        product = {
            'id': int(datetime.datetime.now().timestamp() * 1000),
            'name': data['name'].strip(),
            'sku': data.get('sku', generate_sku()),
            'category': data['category'],
            'color': data['color'].strip(),
            'sizes': data['sizes'],
            'buyPrice': float(data['buyPrice']),
            'minSellPrice': float(data['minSellPrice']),
            'maxSellPrice': float(data['maxSellPrice']),
            'description': data.get('description', '').strip(),
            'image': data.get('image', 'https://via.placeholder.com/300x300?text=Shoe+Image'),
            'storage': data.get('storage', {
                'type': 'backblaze-b2',
                'bucket': Config.B2_BUCKET_ID,
                'bucketName': Config.B2_BUCKET_NAME,
                'endpoint': Config.B2_ENDPOINT,
                'uploadedAt': datetime.datetime.now().isoformat()
            }),
            'dateAdded': datetime.datetime.now().isoformat(),
            'lastUpdated': datetime.datetime.now().isoformat()
        }
        
        product['totalStock'] = calculate_total_stock(product)
        
        products = data_store.get_products()
        products.append(product)
        data_store.save_products(products)
        
        add_notification(f"New product added: {product['name']}", 'success')
        return jsonify(product), 201
    except Exception as e:
        print(f"Error creating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    try:
        data = request.json
        products = data_store.get_products()
        for i, product in enumerate(products):
            if product['id'] == product_id:
                product.update({
                    'name': data.get('name', product['name']),
                    'sku': data.get('sku', product['sku']),
                    'category': data.get('category', product['category']),
                    'color': data.get('color', product['color']),
                    'sizes': data.get('sizes', product['sizes']),
                    'buyPrice': float(data.get('buyPrice', product['buyPrice'])),
                    'minSellPrice': float(data.get('minSellPrice', product['minSellPrice'])),
                    'maxSellPrice': float(data.get('maxSellPrice', product['maxSellPrice'])),
                    'description': data.get('description', product['description']),
                    'image': data.get('image', product['image']),
                    'lastUpdated': datetime.datetime.now().isoformat()
                })
                product['totalStock'] = calculate_total_stock(product)
                data_store.save_products(products)
                add_notification(f"Product updated: {product['name']}", 'info')
                return jsonify(product)
        return jsonify({'error': 'Product not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    products = data_store.get_products()
    for i, product in enumerate(products):
        if product['id'] == product_id:
            deleted = products.pop(i)
            data_store.save_products(products)
            add_notification(f"Product deleted: {deleted['name']}", 'warning')
            return jsonify({'success': True, 'product': deleted})
    return jsonify({'error': 'Product not found'}), 404

# ==================== BACKBLAZE B2 ROUTES ====================

@app.route('/api/b2/upload', methods=['POST'])
@login_required
def upload_to_b2():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
        
        file_data = file.read()
        if len(file_data) > Config.MAX_IMAGE_SIZE:
            return jsonify({'error': 'File size exceeds 20MB'}), 400
        
        result = b2_client.upload_file(file_data, file.filename, file.content_type)
        if result['success']:
            b2_images = data_store.get_b2_images()
            b2_image_record = {
                'id': int(datetime.datetime.now().timestamp() * 1000),
                'url': result['url'],
                'filename': result['filename'],
                'bucket': result.get('bucket'),
                'bucket_id': result.get('bucket_id'),
                'endpoint': result.get('endpoint'),
                'demo_mode': result.get('demo_mode', False),
                'uploadedAt': datetime.datetime.now().isoformat()
            }
            b2_images.append(b2_image_record)
            data_store.save_b2_images(b2_images)
            return jsonify({
                'success': True,
                'url': result['url'],
                'filename': result['filename'],
                'bucket_info': b2_client.get_bucket_info()
            })
        else:
            return jsonify({'error': result.get('error', 'Upload failed')}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2/info', methods=['GET'])
@login_required
def get_b2_info():
    return jsonify(b2_client.get_bucket_info())

@app.route('/api/b2/images', methods=['GET'])
@login_required
def get_b2_images():
    images = data_store.get_b2_images()
    return jsonify(images[-50:])

# ==================== SALE ROUTES ====================

@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    sales = data_store.get_sales()
    sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify(sales)

@app.route('/api/sales', methods=['POST'])
@login_required
def create_sale():
    try:
        data = request.json
        required_fields = ['productId', 'productName', 'productSKU', 'size', 
                          'quantity', 'unitPrice', 'totalAmount', 'totalProfit']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        sale = {
            'id': int(datetime.datetime.now().timestamp() * 1000),
            'timestamp': datetime.datetime.now().isoformat(),
            'statementId': f"{int(datetime.datetime.now().timestamp() * 1000)}-SALE",
            **data
        }
        
        products = data_store.get_products()
        for i, product in enumerate(products):
            if product['id'] == sale['productId']:
                size_key = str(sale['size'])
                if product['sizes'].get(size_key, 0) >= sale['quantity']:
                    product['sizes'][size_key] -= sale['quantity']
                    product['lastUpdated'] = datetime.datetime.now().isoformat()
                    product['totalStock'] = calculate_total_stock(product)
                    data_store.save_products(products)
                    record_monthly_category_sale(
                        product.get('category', 'Other'),
                        sale['totalAmount'],
                        sale['quantity'],
                        sale['totalProfit']
                    )
                    break
                else:
                    return jsonify({'error': 'Insufficient stock'}), 400
        
        sales = data_store.get_sales()
        sales.insert(0, sale)
        data_store.save_sales(sales)
        
        statement = {
            'id': sale['statementId'],
            'saleId': sale['id'],
            'timestamp': sale['timestamp'],
            'productName': sale['productName'],
            'productSKU': sale['productSKU'],
            'productColor': data.get('productColor', 'N/A'),
            'category': data.get('category', 'N/A'),
            'size': sale['size'],
            'quantity': sale['quantity'],
            'unitPrice': sale['unitPrice'],
            'totalAmount': sale['totalAmount'],
            'totalProfit': sale['totalProfit'],
            'customerName': data.get('customerName', 'Walk-in Customer'),
            'isBargain': data.get('isBargain', False),
            'notes': data.get('notes', 'No additional notes')
        }
        
        statements = data_store.get_sale_statements()
        statements.insert(0, statement)
        if len(statements) > 100:
            statements = statements[:100]
        data_store.save_sale_statements(statements)
        
        add_notification(
            f"Sale recorded: {sale['productName']} ({sale['quantity']} × Size {sale['size']})",
            'success'
        )
        
        return jsonify({'success': True, 'sale': sale, 'statement': statement}), 201
    except Exception as e:
        print(f"Error creating sale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/statements', methods=['GET'])
@login_required
def get_sale_statements():
    statements = data_store.get_sale_statements()
    return jsonify(statements)

@app.route('/api/sales/statements/<int:sale_id>', methods=['GET'])
@login_required
def get_sale_statement(sale_id):
    statements = data_store.get_sale_statements()
    statement = next((s for s in statements if s['saleId'] == sale_id), None)
    if statement:
        return jsonify(statement)
    return jsonify({'error': 'Statement not found'}), 404

# ==================== ANALYTICS ROUTES ====================

@app.route('/api/analytics/dashboard', methods=['GET'])
@login_required
def get_dashboard_data():
    try:
        period = request.args.get('period', 'today')
        sales = data_store.get_sales()
        products = data_store.get_products()
        
        now = datetime.datetime.now()
        start_date = now
        
        if period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == '7days':
            start_date = now - datetime.timedelta(days=7)
        elif period == '1month':
            start_date = now - datetime.timedelta(days=30)
        elif period == '6months':
            start_date = now - datetime.timedelta(days=180)
        elif period == '12months':
            start_date = now - datetime.timedelta(days=365)
        
        filtered_sales = []
        for s in sales:
            try:
                if datetime.datetime.fromisoformat(s['timestamp']) >= start_date:
                    filtered_sales.append(s)
            except:
                pass
        
        total_revenue = sum(s.get('totalAmount', 0) for s in filtered_sales)
        total_profit = sum(s.get('totalProfit', 0) for s in filtered_sales)
        total_stock = sum(p.get('totalStock', 0) for p in products)
        total_products = len(products)
        
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_sales = []
        for s in sales:
            try:
                if datetime.datetime.fromisoformat(s['timestamp']) >= today_start:
                    today_sales.append(s)
            except:
                pass
        
        today_revenue = sum(s.get('totalAmount', 0) for s in today_sales)
        today_profit = sum(s.get('totalProfit', 0) for s in today_sales)
        today_items = sum(s.get('quantity', 0) for s in today_sales)
        
        product_sales = {}
        for sale in filtered_sales:
            name = sale.get('productName', 'Unknown')
            product_sales[name] = product_sales.get(name, 0) + sale.get('quantity', 0)
        
        top_products = [
            {'name': k, 'units': v} 
            for k, v in sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
        ]
        
        daily_sales = {}
        for i in range(30):
            date = now - datetime.timedelta(days=i)
            date_str = date.strftime('%Y-%m-%d')
            daily_sales[date_str] = 0
        
        for sale in filtered_sales:
            try:
                sale_date = datetime.datetime.fromisoformat(sale['timestamp']).strftime('%Y-%m-%d')
                if sale_date in daily_sales:
                    daily_sales[sale_date] += sale.get('totalAmount', 0)
            except:
                pass
        
        return jsonify({
            'period': period,
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'totalStock': total_stock,
            'totalProducts': total_products,
            'todayRevenue': today_revenue,
            'todayProfit': today_profit,
            'todayItems': today_items,
            'topProducts': top_products,
            'dailySales': [
                {'date': date, 'revenue': amount}
                for date, amount in sorted(daily_sales.items())
            ]
        })
    except Exception as e:
        print(f"Dashboard error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/categories', methods=['GET'])
@login_required
def get_category_analytics():
    try:
        period = request.args.get('period', 'current')
        category_sales = data_store.get_category_sales()
        now = datetime.datetime.now()
        
        if period == 'current':
            month_key = now.strftime('%Y-%m')
            month_data = category_sales.get(month_key, {})
            rankings = []
            total_revenue = sum(c.get('revenue', 0) for c in month_data.values())
            
            for category, data in month_data.items():
                market_share = (data.get('revenue', 0) / total_revenue * 100) if total_revenue > 0 else 0
                
                demand_level = 'Medium'
                if data.get('revenue', 0) > 50000:
                    demand_level = 'Very High'
                elif data.get('revenue', 0) > 20000:
                    demand_level = 'High'
                elif data.get('revenue', 0) < 5000:
                    demand_level = 'Low'
                elif data.get('revenue', 0) < 1000:
                    demand_level = 'Very Low'
                
                rankings.append({
                    'category': category,
                    'revenue': data.get('revenue', 0),
                    'quantity': data.get('quantity', 0),
                    'profit': data.get('profit', 0),
                    'marketShare': round(market_share, 1),
                    'demandLevel': demand_level
                })
            
            rankings.sort(key=lambda x: x['revenue'], reverse=True)
            
            return jsonify({
                'period': period,
                'month': now.strftime('%B %Y'),
                'rankings': rankings,
                'totalRevenue': total_revenue,
                'totalQuantity': sum(c.get('quantity', 0) for c in month_data.values()),
                'totalProfit': sum(c.get('profit', 0) for c in month_data.values())
            })
        else:
            return jsonify({'rankings': [], 'totalRevenue': 0, 'totalQuantity': 0, 'totalProfit': 0})
    except Exception as e:
        print(f"Category analytics error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/budget', methods=['GET'])
@login_required
def get_budget_plan():
    try:
        sales = data_store.get_sales()
        now = datetime.datetime.now()
        start_date = now - datetime.timedelta(days=14)
        
        recent_sales = []
        for s in sales:
            try:
                if datetime.datetime.fromisoformat(s['timestamp']) >= start_date:
                    recent_sales.append(s)
            except:
                pass
        
        total_revenue = sum(s.get('totalAmount', 0) for s in recent_sales)
        total_profit = sum(s.get('totalProfit', 0) for s in recent_sales)
        avg_daily_revenue = total_revenue / 14 if total_revenue > 0 else 0
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        weekly_budget = max(total_profit * 0.3, 1000)
        
        budget_allocation = [
            {'category': 'High Demand Products', 'percentage': 50, 'amount': weekly_budget * 0.5},
            {'category': 'Restock Fast Movers', 'percentage': 30, 'amount': weekly_budget * 0.3},
            {'category': 'New Opportunities', 'percentage': 15, 'amount': weekly_budget * 0.15},
            {'category': 'Emergency Buffer', 'percentage': 5, 'amount': weekly_budget * 0.05}
        ]
        
        recommendation = (
            f"Based on last 2 weeks' profit of {format_currency(total_profit)} "
            f"({profit_margin:.1f}% margin), allocate {format_currency(weekly_budget)} for inventory."
        ) if total_profit > 0 else "Not enough data for budget planning. Start making more sales."
        
        return jsonify({
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'avgDailyRevenue': avg_daily_revenue,
            'profitMargin': round(profit_margin, 1),
            'weeklyBudget': weekly_budget,
            'highDemand': [],
            'lowDemand': [],
            'restockRecommendations': [],
            'budgetAllocation': budget_allocation,
            'recommendation': recommendation
        })
    except Exception as e:
        print(f"Budget plan error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/stock-alerts', methods=['GET'])
@login_required
def get_stock_alerts():
    try:
        products = data_store.get_products()
        alerts = []
        now = datetime.datetime.now()
        
        for product in products:
            if product.get('sizes'):
                for size, stock in product['sizes'].items():
                    if stock > 0 and stock <= Config.LOW_STOCK_THRESHOLD:
                        alerts.append({
                            'type': 'low_stock',
                            'product': product.get('name'),
                            'size': size,
                            'stock': stock,
                            'message': f"{product.get('name')} (Size {size}) is running low - only {stock} left!"
                        })
            
            try:
                date_added = datetime.datetime.fromisoformat(product.get('dateAdded', now.isoformat()))
                days_in_stock = (now - date_added).days
                if days_in_stock >= Config.OLD_STOCK_DAYS and product.get('totalStock', 0) > 0:
                    alerts.append({
                        'type': 'old_stock',
                        'product': product.get('name'),
                        'daysInStock': days_in_stock,
                        'stock': product.get('totalStock', 0),
                        'message': f"{product.get('name')} has been in stock for {days_in_stock} days - consider promotions!"
                    })
            except:
                pass
        
        return jsonify(alerts)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/business-plan', methods=['GET'])
@login_required
def get_business_plan():
    try:
        sales = data_store.get_sales()
        products = data_store.get_products()
        
        total_revenue = sum(s.get('totalAmount', 0) for s in sales)
        total_profit = sum(s.get('totalProfit', 0) for s in sales)
        
        tithe = total_profit * (Config.TITHE_PERCENTAGE / 100)
        savings = total_profit * (Config.SAVINGS_PERCENTAGE / 100)
        restock = total_profit * (Config.RESTOCK_PERCENTAGE / 100)
        deductions = total_profit * (Config.DEDUCTIONS_PERCENTAGE / 100)
        personal_income = total_profit * (Config.PERSONAL_INCOME_PERCENTAGE / 100)
        
        stock_value = sum(
            p.get('totalStock', 0) * p.get('buyPrice', 0) 
            for p in products
        )
        
        revenue_score = min(100, (total_revenue / 100000) * 100) if total_revenue > 0 else 0
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        profit_score = min(100, profit_margin * 2)
        inventory_score = min(100, (stock_value / 50000) * 100)
        
        health_score = int((revenue_score * 0.4) + (profit_score * 0.3) + (inventory_score * 0.3))
        
        if health_score < 30:
            health_status = 'Needs Improvement'
        elif health_score < 50:
            health_status = 'Fair'
        elif health_score < 70:
            health_status = 'Good'
        elif health_score < 85:
            health_status = 'Very Good'
        else:
            health_status = 'Excellent'
        
        return jsonify({
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'tithe': tithe,
            'savings': savings,
            'restock': restock,
            'deductions': deductions,
            'personalIncome': personal_income,
            'healthScore': health_score,
            'healthStatus': health_status,
            'healthBreakdown': {
                'revenue': revenue_score,
                'profit': profit_score,
                'inventory': inventory_score
            }
        })
    except Exception as e:
        print(f"Business plan error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== NOTIFICATION ROUTES ====================

@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    limit = int(request.args.get('limit', 50))
    notifications = data_store.get_notifications()
    notifications.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    return jsonify(notifications[:limit])

@app.route('/api/notifications/unread-count', methods=['GET'])
@login_required
def get_unread_count():
    notifications = data_store.get_notifications()
    unread_count = sum(1 for n in notifications if not n.get('read', False))
    return jsonify({'count': unread_count})

@app.route('/api/notifications/mark-read', methods=['POST'])
@login_required
def mark_notifications_read():
    notifications = data_store.get_notifications()
    for notification in notifications:
        notification['read'] = True
    data_store.save_notifications(notifications)
    return jsonify({'success': True})

@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notifications = data_store.get_notifications()
    for notification in notifications:
        if notification['id'] == notification_id:
            notification['read'] = True
            data_store.save_notifications(notifications)
            return jsonify({'success': True})
    return jsonify({'error': 'Notification not found'}), 404

# ==================== HEALTH CHECK ====================

@app.route('/health')
def health_check():
    b2_status = 'connected' if b2_client.is_initialized() else 'demo_mode'
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.datetime.now().isoformat(),
        'app': 'Karanja Shoe Store',
        'version': '1.0.0',
        'created': 'February 9, 2026',
        'b2_status': b2_status,
        'b2_bucket': Config.B2_BUCKET_NAME
    })

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return render_template('index.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

# ==================== MAIN ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)
