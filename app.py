from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
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
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== PRODUCTION CONFIGURATION ====================
# Load from environment variables - NEVER hardcode credentials
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', os.urandom(24).hex())
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['STATIC_FOLDER'] = 'static'

# ==================== SUPABASE POSTGRESQL CONFIGURATION ====================
# Get DATABASE_URL from environment - REQUIRED for production
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
if not app.config['SQLALCHEMY_DATABASE_URI']:
    raise ValueError("❌ DATABASE_URL environment variable is not set. Supabase PostgreSQL connection required.")

# Fix for Supabase SSL requirement - ensure SSL mode is enabled
if '?' not in app.config['SQLALCHEMY_DATABASE_URI']:
    app.config['SQLALCHEMY_DATABASE_URI'] += '?sslmode=require'
elif 'sslmode' not in app.config['SQLALCHEMY_DATABASE_URI']:
    app.config['SQLALCHEMY_DATABASE_URI'] += '&sslmode=require'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 300,
    'pool_pre_ping': True,
    'connect_args': {
        'connect_timeout': 10,
        'keepalives': 1,
        'keepalives_idle': 30,
        'keepalives_interval': 10,
        'keepalives_count': 5
    }
}

# Initialize SQLAlchemy with Supabase
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ==================== BACKBLAZE B2 CONFIGURATION ====================
# Load B2 credentials from environment
B2_CONFIG = {
    'BUCKET_NAME': os.environ.get('B2_BUCKET_NAME', 'karanjastores'),
    'BUCKET_ID': os.environ.get('B2_BUCKET_ID', 'd33891d14fc8555f99c8001c'),
    'ENDPOINT': os.environ.get('B2_ENDPOINT', 's3.eu-central-003.backblazeb2.com'),
    'REGION': os.environ.get('B2_REGION', 'eu-central-003'),
    'CDN_URL': os.environ.get('B2_CDN_URL', 'https://f005.backblazeb2.com/file/karanjastores'),
    'CREATED_DATE': 'February 13, 2026',
    'ACCESS_KEY_ID': os.environ.get('B2_ACCESS_KEY_ID'),
    'SECRET_ACCESS_KEY': os.environ.get('B2_SECRET_ACCESS_KEY'),
    'TYPE': 'Private',
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

# Initialize Backblaze B2 client (for image storage only)
b2_client = None
if B2_CONFIG['ACCESS_KEY_ID'] and B2_CONFIG['SECRET_ACCESS_KEY']:
    try:
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
        logger.info("✓ Backblaze B2 client initialized successfully")
    except Exception as e:
        logger.error(f"✗ Failed to initialize B2 client: {e}")
        b2_client = None
else:
    logger.warning("⚠ B2 credentials not set. Image uploads will be stored locally.")

# Create static folders
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static', exist_ok=True)

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

# ==================== DATABASE MODELS (Supabase PostgreSQL) ====================

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), default='admin')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'role': self.role,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Product(db.Model):
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    color = db.Column(db.String(50))
    price = db.Column(db.Float, default=0)
    buy_price = db.Column(db.Float, default=0)
    min_sell_price = db.Column(db.Float, default=0)
    max_sell_price = db.Column(db.Float, default=0)
    total_stock = db.Column(db.Integer, default=0)
    sizes = db.Column(db.JSON, default={})
    image = db.Column(db.String(500))
    s3_key = db.Column(db.String(500))
    image_source = db.Column(db.String(50), default='placeholder')
    date_added = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sku': self.sku,
            'description': self.description,
            'category': self.category,
            'color': self.color,
            'price': self.price,
            'buyPrice': self.buy_price,
            'minSellPrice': self.min_sell_price,
            'maxSellPrice': self.max_sell_price,
            'totalStock': self.total_stock,
            'sizes': self.sizes,
            'image': self.image,
            's3_key': self.s3_key,
            'image_source': self.image_source,
            'dateAdded': self.date_added.isoformat() if self.date_added else None,
            'lastUpdated': self.last_updated.isoformat() if self.last_updated else None
        }

class Sale(db.Model):
    __tablename__ = 'sales'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    product_name = db.Column(db.String(200))
    product_sku = db.Column(db.String(50))
    size = db.Column(db.String(20))
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, default=0)
    total_amount = db.Column(db.Float, default=0)
    total_profit = db.Column(db.Column(db.Float, default=0))
    customer_name = db.Column(db.String(100), default='Walk-in Customer')
    notes = db.Column(db.Text)
    is_bargain = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'productId': self.product_id,
            'productName': self.product_name,
            'productSKU': self.product_sku,
            'size': self.size,
            'quantity': self.quantity,
            'unitPrice': self.unit_price,
            'totalAmount': self.total_amount,
            'totalProfit': self.total_profit,
            'customerName': self.customer_name,
            'notes': self.notes,
            'isBargain': self.is_bargain,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class Notification(db.Model):
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')
    read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'type': self.type,
            'read': self.read,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }

class B2Image(db.Model):
    __tablename__ = 'b2_images'
    
    id = db.Column(db.String(36), primary_key=True)
    signed_url = db.Column(db.String(500))
    s3_key = db.Column(db.String(500))
    file_name = db.Column(db.String(200))
    bucket_id = db.Column(db.String(100))
    bucket_name = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'signed_url': self.signed_url,
            's3_key': self.s3_key,
            'fileName': self.file_name,
            'bucketId': self.bucket_id,
            'bucketName': self.bucket_name,
            'uploadedAt': self.uploaded_at.isoformat() if self.uploaded_at else None
        }

class Setting(db.Model):
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True)
    value = db.Column(db.JSON)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class MonthlyCategorySale(db.Model):
    __tablename__ = 'monthly_category_sales'
    
    id = db.Column(db.Integer, primary_key=True)
    month_key = db.Column(db.String(20))
    category = db.Column(db.String(100))
    revenue = db.Column(db.Float, default=0)
    quantity = db.Column(db.Integer, default=0)
    profit = db.Column(db.Float, default=0)
    
    __table_args__ = (db.UniqueConstraint('month_key', 'category', name='_month_category_uc'),)

class DailyStatement(db.Model):
    __tablename__ = 'daily_statements'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.DateTime, unique=True)
    total_revenue = db.Column(db.Float, default=0)
    total_profit = db.Column(db.Float, default=0)
    total_items = db.Column(db.Integer, default=0)
    bargain_sales = db.Column(db.Integer, default=0)
    sales_count = db.Column(db.Integer, default=0)
    avg_sale_value = db.Column(db.Float, default=0)
    category_breakdown = db.Column(db.JSON, default={})
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

class SaleStatement(db.Model):
    __tablename__ = 'sale_statements'
    
    id = db.Column(db.String(50), primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sales.id'))
    product_name = db.Column(db.String(200))
    product_sku = db.Column(db.String(50))
    product_color = db.Column(db.String(50))
    category = db.Column(db.String(100))
    size = db.Column(db.String(20))
    quantity = db.Column(db.Integer)
    unit_price = db.Column(db.Float)
    total_amount = db.Column(db.Float)
    total_profit = db.Column(db.Float)
    customer_name = db.Column(db.String(100))
    is_bargain = db.Column(db.Boolean)
    notes = db.Column(db.Text)
    timestamp = db.Column(db.DateTime)

class BudgetPlan(db.Model):
    __tablename__ = 'budget_plans'
    
    id = db.Column(db.Integer, primary_key=True)
    period_start = db.Column(db.DateTime)
    period_end = db.Column(db.DateTime)
    total_revenue = db.Column(db.Float)
    total_profit = db.Column(db.Float)
    weekly_budget = db.Column(db.Float)
    profit_margin = db.Column(db.Float)
    recommendation = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================== CREATE TABLES ====================
with app.app_context():
    try:
        db.create_all()
        logger.info("✓ Supabase PostgreSQL tables created/verified successfully")
        
        # Create default admin user if none exists
        if not User.query.first():
            admin_password = bcrypt.generate_password_hash('admin123').decode('utf-8')
            admin_user = User(
                email='admin@karanjashoes.com',
                password=admin_password,
                name='Admin Karanja',
                role='admin'
            )
            db.session.add(admin_user)
            db.session.commit()
            logger.info("✓ Default admin user created in Supabase")
            
            # Add welcome notification
            welcome_notification = Notification(
                message='Welcome to Karanja Shoe Store! Database: Supabase PostgreSQL',
                type='info',
                read=False
            )
            db.session.add(welcome_notification)
            db.session.commit()
            
    except Exception as e:
        logger.error(f"✗ Database initialization error: {e}")
        raise

# ==================== BACKBLAZE B2 HELPER FUNCTIONS ====================
def generate_signed_url(s3_key, expiration=604800):
    """Generate a pre-signed URL for private B2 bucket access"""
    if not b2_client or not s3_key:
        return None
    
    try:
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
    if not b2_client:
        return jsonify({'error': 'Backblaze B2 is not configured'}), 503
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
        
        file = request.files['image']
        
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        # Generate unique filename
        timestamp = int(datetime.utcnow().timestamp())
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
                    'uploaded_at': datetime.utcnow().isoformat()
                }
            }
        )
        
        logger.info(f"✓ Successfully uploaded image to B2: {s3_key}")
        
        # Generate signed URL
        signed_url = generate_signed_url(s3_key, expiration=604800)
        
        # Store record in PostgreSQL
        image_record = B2Image(
            id=str(uuid.uuid4()),
            signed_url=signed_url,
            s3_key=s3_key,
            file_name=unique_filename,
            bucket_id=B2_CONFIG['BUCKET_ID'],
            bucket_name=B2_CONFIG['BUCKET_NAME']
        )
        db.session.add(image_record)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'url': signed_url,
            'signed_url': signed_url,
            'fileName': unique_filename,
            's3_key': s3_key
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error uploading to B2: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with fresh signed URLs"""
    try:
        products = Product.query.order_by(Product.date_added.desc()).all()
        
        products_copy = []
        for product in products:
            product_dict = product.to_dict()
            
            # Generate fresh signed URL for B2 images
            if product.s3_key and b2_client:
                fresh_url = generate_signed_url(product.s3_key, expiration=86400)
                if fresh_url:
                    product_dict['image'] = fresh_url
            
            products_copy.append(product_dict)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint to get products - NO LOGIN REQUIRED"""
    try:
        products = Product.query.order_by(Product.date_added.desc()).all()
        
        products_copy = []
        for product in products:
            product_dict = product.to_dict()
            
            # Remove sensitive data
            product_dict.pop('buyPrice', None)
            product_dict.pop('createdBy', None)
            
            # Generate fresh signed URL for B2 images
            if product.s3_key and b2_client:
                fresh_url = generate_signed_url(product.s3_key, expiration=86400)
                if fresh_url:
                    product_dict['image'] = fresh_url
            
            products_copy.append(product_dict)
        
        return jsonify(products_copy), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
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
        if s3_key and b2_client:
            signed_url = generate_signed_url(s3_key, expiration=604800)
        
        # Create product in PostgreSQL
        product = Product(
            name=name.strip(),
            sku=sku,
            description=description.strip(),
            category=category,
            color=color,
            sizes=sizes,
            price=float(max_sell_price) if max_sell_price else 0,
            buy_price=float(buy_price) if buy_price else 0,
            min_sell_price=float(min_sell_price) if min_sell_price else 0,
            max_sell_price=float(max_sell_price) if max_sell_price else 0,
            total_stock=total_stock,
            created_by=int(get_jwt_identity())
        )
        
        # Handle image
        if signed_url:
            product.image = signed_url
            product.s3_key = s3_key
            product.image_source = 'b2'
        elif image_url and image_url.startswith('/static/'):
            product.image = image_url
            product.image_source = 'local'
        elif image_url and image_url.startswith('http'):
            product.image = image_url
            product.image_source = 'external'
        else:
            product.image = '/static/placeholder.png'
            product.image_source = 'placeholder'
        
        db.session.add(product)
        db.session.commit()
        
        # Add notification
        notification = Notification(
            message=f'New product added: {product.name}',
            type='success',
            read=False
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Product uploaded successfully!',
            'product': product.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating product: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update existing product"""
    try:
        product = Product.query.get(product_id)
        
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
            product.name = name.strip()
        if description is not None:
            product.description = description.strip()
        if category:
            product.category = category
        if color is not None:
            product.color = color
        if sku:
            product.sku = sku
        if buy_price:
            product.buy_price = float(buy_price)
        if min_sell_price:
            product.min_sell_price = float(min_sell_price)
        if max_sell_price:
            product.max_sell_price = float(max_sell_price)
            product.price = float(max_sell_price)
        
        # Update sizes
        if sizes_json:
            try:
                sizes = json.loads(sizes_json)
                product.sizes = sizes
                
                # Recalculate total stock
                total_stock = 0
                for size, stock in sizes.items():
                    try:
                        total_stock += int(stock) if stock and int(stock) > 0 else 0
                    except:
                        pass
                product.total_stock = total_stock
            except:
                pass
        
        # Update image
        if image_url:
            s3_key = extract_s3_key_from_url(image_url)
            if s3_key and b2_client:
                product.s3_key = s3_key
                product.image = generate_signed_url(s3_key, expiration=604800)
                product.image_source = 'b2'
            elif image_url.startswith('/static/'):
                product.image = image_url
                product.image_source = 'local'
            else:
                product.image = image_url
                product.image_source = 'external'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully!',
            'product': product.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    try:
        product = Product.query.get(product_id)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Store name for notification
        product_name = product.name
        
        db.session.delete(product)
        db.session.commit()
        
        # Add notification
        notification = Notification(
            message=f'Product deleted: {product_name}',
            type='warning',
            read=False
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Product deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

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
        
        product = Product.query.get(product_id)
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        size_key = str(size)
        sizes = product.sizes or {}
        if size_key not in sizes or sizes[size_key] < quantity:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Update stock
        sizes[size_key] -= quantity
        if sizes[size_key] < 0:
            sizes[size_key] = 0
        product.sizes = sizes
        
        # Recalculate total stock
        total_stock = 0
        for stock in sizes.values():
            total_stock += stock if stock > 0 else 0
        product.total_stock = total_stock
        
        # Calculate amounts
        total_amount = unit_price * quantity
        total_cost = product.buy_price * quantity
        total_profit = total_amount - total_cost
        
        # Create sale record
        sale = Sale(
            product_id=product_id,
            product_name=product.name,
            product_sku=product.sku,
            size=size,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_amount,
            total_profit=total_profit,
            customer_name=customer_name,
            notes=notes,
            is_bargain=is_bargain
        )
        
        db.session.add(sale)
        db.session.commit()
        
        # Create sale statement
        statement_id = f"STMT-{sale.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        sale_statement = SaleStatement(
            id=statement_id,
            sale_id=sale.id,
            product_name=product.name,
            product_sku=product.sku,
            product_color=product.color or 'N/A',
            category=product.category,
            size=size,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_amount,
            total_profit=total_profit,
            customer_name=customer_name,
            is_bargain=is_bargain,
            notes=notes,
            timestamp=sale.timestamp
        )
        db.session.add(sale_statement)
        
        # Add notification
        notification = Notification(
            message=f'Sale recorded: {product.name} ({quantity} × Size {size})',
            type='success',
            read=False
        )
        db.session.add(notification)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'sale': sale.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating sale: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales"""
    try:
        sales = Sale.query.order_by(Sale.timestamp.desc()).all()
        return jsonify([sale.to_dict() for sale in sales]), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

# ==================== NOTIFICATION ROUTES ====================
@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    try:
        notifications = Notification.query.order_by(Notification.timestamp.desc()).limit(50).all()
        return jsonify([n.to_dict() for n in notifications]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_unread_notification_count():
    """Get unread notification count"""
    try:
        unread_count = Notification.query.filter_by(read=False).count()
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting unread count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        notification = Notification.query.get(notification_id)
        
        if notification:
            notification.read = True
            db.session.commit()
            return jsonify({'success': True}), 200
        
        return jsonify({'error': 'Notification not found'}), 404
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking notification read: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== DASHBOARD STATS ====================
@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        total_products = Product.query.count()
        total_stock = db.session.query(db.func.sum(Product.total_stock)).scalar() or 0
        
        total_revenue = db.session.query(db.func.sum(Sale.total_amount)).scalar() or 0
        total_profit = db.session.query(db.func.sum(Sale.total_profit)).scalar() or 0
        
        # Get today's sales
        today = datetime.utcnow().date()
        today_sales = Sale.query.filter(
            db.func.date(Sale.timestamp) == today
        ).all()
        
        today_revenue = sum(s.total_amount for s in today_sales)
        today_profit = sum(s.total_profit for s in today_sales)
        today_items = sum(s.quantity for s in today_sales)
        
        return jsonify({
            'totalProducts': total_products,
            'totalStock': total_stock,
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'todayRevenue': today_revenue,
            'todayProfit': today_profit,
            'todayItems': today_items,
            'salesCount': Sale.query.count(),
            'storage_type': 'supabase',
            'database': 'postgresql'
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
            'storage_type': 'supabase',
            'database': 'postgresql'
        }), 200

# ==================== B2 INFO ROUTES ====================
@app.route('/api/b2/info', methods=['GET'])
@jwt_required()
def get_b2_info():
    """Get Backblaze B2 bucket information"""
    try:
        images_count = B2Image.query.count()
        
        return jsonify({
            'bucketId': B2_CONFIG['BUCKET_ID'],
            'bucketName': B2_CONFIG['BUCKET_NAME'],
            'endpoint': B2_CONFIG['ENDPOINT'],
            'region': B2_CONFIG['REGION'],
            'created': B2_CONFIG['CREATED_DATE'],
            'cdn_url': B2_CONFIG['CDN_URL'],
            'type': B2_CONFIG['TYPE'],
            'stored_images': images_count,
            'connected': b2_client is not None,
            'storage_type': 'b2'
        }), 200
    except Exception as e:
        logger.error(f"Error getting B2 info: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== STATIC FILE SERVING ====================
@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except Exception as e:
        logger.error(f"Error serving static file {filename}: {e}")
        return jsonify({'error': 'Static file not found'}), 404

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    """Serve uploaded files"""
    try:
        return send_from_directory('static/uploads', filename)
    except Exception as e:
        logger.error(f"Error serving upload {filename}: {e}")
        return jsonify({'error': 'Uploaded file not found'}), 404

@app.route('/favicon.ico')
def favicon():
    """Serve favicon"""
    try:
        return send_from_directory('static', 'favicon.ico')
    except:
        return '', 204

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
        
        user = User.query.filter_by(email=email).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            access_token = create_access_token(
                identity=str(user.id),
                additional_claims={
                    'email': user.email,
                    'name': user.name,
                    'role': user.role
                }
            )
            
            return jsonify({
                'success': True,
                'token': access_token,
                'user': user.to_dict()
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
        user = User.query.get(int(current_user_id))
        
        if user:
            return jsonify(user.to_dict()), 200
        
        return jsonify({'error': 'User not found'}), 404
        
    except Exception as e:
        logger.error(f"Error getting current user: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint for Render"""
    try:
        # Test database connection
        db.session.execute('SELECT 1')
        db_status = 'connected'
        
        # Test B2 connection
        b2_status = 'connected' if b2_client else 'disabled'
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'app': 'Karanja Shoe Store',
            'database': {
                'type': 'supabase_postgresql',
                'status': db_status,
                'pool_size': app.config['SQLALCHEMY_ENGINE_OPTIONS']['pool_size']
            },
            'storage': {
                'type': 'backblaze_b2',
                'status': b2_status,
                'bucket': B2_CONFIG['BUCKET_NAME'] if b2_client else None
            },
            'products': Product.query.count(),
            'sales': Sale.query.count(),
            'users': User.query.count()
        }), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'degraded',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

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
                'database': 'Supabase PostgreSQL',
                'storage': 'Backblaze B2',
                'products': Product.query.count(),
                'status': 'online',
                'endpoints': {
                    'health': '/api/health',
                    'login': '/api/auth/login',
                    'products': '/api/products',
                    'public_products': '/api/public/products',
                    'sales': '/api/sales',
                    'b2_upload': '/api/b2/upload',
                    'b2_info': '/api/b2/info'
                }
            }), 200
    except Exception as e:
        logger.error(f"Error serving index: {e}")
        return jsonify({'error': 'Could not load index.html'}), 500

# ==================== CATCH-ALL ROUTE FOR SPA ====================
@app.route('/<path:path>')
def catch_all(path):
    """Serve index.html for all non-API and non-static routes"""
    if path.startswith('api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    if path.startswith('static/'):
        return jsonify({'error': 'Static file not found'}), 404
    
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
    logger.info("✓ KARANJA SHOE STORE - PRODUCTION MODE")
    logger.info(f"  Database: Supabase PostgreSQL")
    logger.info(f"  Database URL: {app.config['SQLALCHEMY_DATABASE_URI'].split('@')[1].split('/')[0]}")
    logger.info(f"  Storage: {'Backblaze B2' if b2_client else 'Local'}")
    logger.info(f"  Environment: {'Production' if os.environ.get('RENDER') else 'Development'}")
    logger.info("=" * 70)
    
    app.run(host='0.0.0.0', port=port, debug=False)
