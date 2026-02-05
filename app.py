"""
Karanja Shoe Store - Admin Backend System
Complete backend for admin dashboard with authentication, product management,
finance tracking, and analytics.
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from functools import wraps
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, 
    get_jwt_identity, get_jwt
)
import pandas as pd
from PIL import Image
import io

# Initialize Flask app
app = Flask(__name__, static_folder='static')
CORS(app)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', secrets.token_hex(32))
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///karanja_shoe_store.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/products'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Database Models
class Admin(db.Model):
    """Admin user model"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'full_name': self.full_name,
            'phone': self.phone,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class Product(db.Model):
    """Product model for shoes"""
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False)
    size = db.Column(db.String(10), nullable=False)
    color = db.Column(db.String(30))
    material = db.Column(db.String(100))
    
    # Pricing
    cost_price = db.Column(db.Float, nullable=False)  # Price bought
    selling_price = db.Column(db.Float, nullable=False)  # Price to sell
    
    # Stock management
    stock_quantity = db.Column(db.Integer, default=0)
    reorder_level = db.Column(db.Integer, default=5)
    initial_stock = db.Column(db.Integer, default=0)
    
    # Images
    image_url = db.Column(db.String(500))
    image_path = db.Column(db.String(500))
    
    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    sales = db.relationship('Sale', backref='product', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'sku': self.sku,
            'name': self.name,
            'description': self.description,
            'category': self.category,
            'size': self.size,
            'color': self.color,
            'material': self.material,
            'cost_price': self.cost_price,
            'selling_price': self.selling_price,
            'stock_quantity': self.stock_quantity,
            'reorder_level': self.reorder_level,
            'initial_stock': self.initial_stock,
            'image_url': self.image_url,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'profit_per_unit': self.selling_price - self.cost_price,
            'profit_margin': ((self.selling_price - self.cost_price) / self.cost_price * 100) if self.cost_price > 0 else 0,
            'stock_value': self.cost_price * self.stock_quantity,
            'potential_revenue': self.selling_price * self.stock_quantity,
            'total_profit_potential': (self.selling_price - self.cost_price) * self.stock_quantity
        }

class Sale(db.Model):
    """Sales transactions"""
    id = db.Column(db.Integer, primary_key=True)
    transaction_id = db.Column(db.String(50), unique=True, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    profit = db.Column(db.Float, nullable=False)  # profit = (selling - cost) * quantity
    payment_method = db.Column(db.String(50))  # mpesa, cash, card
    mpesa_receipt = db.Column(db.String(100))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    status = db.Column(db.String(20), default='completed')  # pending, completed, cancelled
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'transaction_id': self.transaction_id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'total_amount': self.total_amount,
            'profit': self.profit,
            'payment_method': self.payment_method,
            'mpesa_receipt': self.mpesa_receipt,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'status': self.status,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

class Customer(db.Model):
    """Customer model"""
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    address = db.Column(db.Text)
    total_spent = db.Column(db.Float, default=0)
    total_orders = db.Column(db.Integer, default=0)
    last_purchase = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    sales = db.relationship('Sale', backref='customer_rel', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'total_spent': self.total_spent,
            'total_orders': self.total_orders,
            'last_purchase': self.last_purchase.isoformat() if self.last_purchase else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'average_order_value': self.total_spent / self.total_orders if self.total_orders > 0 else 0
        }

class StockAlert(db.Model):
    """Stock alerts for low stock"""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    alert_type = db.Column(db.String(20))  # low_stock, out_of_stock, reorder
    current_stock = db.Column(db.Integer)
    threshold = db.Column(db.Integer)
    is_resolved = db.Column(db.Boolean, default=False)
    resolved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product.name if self.product else None,
            'alert_type': self.alert_type,
            'current_stock': self.current_stock,
            'threshold': self.threshold,
            'is_resolved': self.is_resolved,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

# Helper Functions
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def save_product_image(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # Add timestamp to avoid collisions
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)
        
        # Generate URL for the image
        image_url = f"/static/uploads/products/{unique_filename}"
        return image_url, filepath
    return None, None

def generate_sku(category, size):
    """Generate SKU based on category and size"""
    category_code = ''.join([word[0].upper() for word in category.split()])
    timestamp = datetime.now().strftime('%y%m%d')
    random_num = secrets.randbelow(1000)
    return f"{category_code}{size}{timestamp}{random_num:03d}"

def calculate_dashboard_stats():
    """Calculate dashboard statistics"""
    # Total products
    total_products = Product.query.count()
    
    # Active products
    active_products = Product.query.filter_by(is_active=True).count()
    
    # Total stock value (based on cost price)
    products = Product.query.all()
    total_stock_value = sum(p.cost_price * p.stock_quantity for p in products)
    total_potential_revenue = sum(p.selling_price * p.stock_quantity for p in products)
    total_profit_potential = total_potential_revenue - total_stock_value
    
    # Low stock items
    low_stock_items = Product.query.filter(
        Product.stock_quantity <= Product.reorder_level,
        Product.stock_quantity > 0
    ).count()
    
    # Out of stock items
    out_of_stock_items = Product.query.filter_by(stock_quantity=0).count()
    
    # Sales statistics (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_sales = Sale.query.filter(Sale.created_at >= thirty_days_ago).all()
    
    total_sales_amount = sum(sale.total_amount for sale in recent_sales)
    total_sales_profit = sum(sale.profit for sale in recent_sales)
    total_sales_count = len(recent_sales)
    
    # Customer statistics
    total_customers = Customer.query.count()
    recent_customers = Customer.query.filter(
        Customer.created_at >= thirty_days_ago
    ).count()
    
    return {
        'total_products': total_products,
        'active_products': active_products,
        'total_stock_value': total_stock_value,
        'total_potential_revenue': total_potential_revenue,
        'total_profit_potential': total_profit_potential,
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'total_sales_amount': total_sales_amount,
        'total_sales_profit': total_sales_profit,
        'total_sales_count': total_sales_count,
        'total_customers': total_customers,
        'recent_customers': recent_customers
    }

def get_sales_trends(days=30):
    """Get sales trends for the last N days"""
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)
    
    # Group sales by day
    daily_sales = db.session.query(
        db.func.date(Sale.created_at).label('date'),
        db.func.sum(Sale.total_amount).label('amount'),
        db.func.sum(Sale.profit).label('profit'),
        db.func.count(Sale.id).label('count')
    ).filter(
        Sale.created_at >= start_date,
        Sale.created_at <= end_date
    ).group_by(
        db.func.date(Sale.created_at)
    ).order_by('date').all()
    
    # Generate date range
    date_range = []
    current_date = start_date
    while current_date <= end_date:
        date_range.append(current_date.date())
        current_date += timedelta(days=1)
    
    # Create data structure
    sales_data = []
    profit_data = []
    count_data = []
    
    for date in date_range:
        # Find sales for this date
        daily = next((d for d in daily_sales if d.date == date), None)
        sales_data.append(daily.amount if daily else 0)
        profit_data.append(daily.profit if daily else 0)
        count_data.append(daily.count if daily else 0)
    
    return {
        'dates': [d.strftime('%Y-%m-%d') for d in date_range],
        'sales': sales_data,
        'profits': profit_data,
        'counts': count_data
    }

def get_category_analysis():
    """Get analysis by category"""
    categories = db.session.query(
        Product.category,
        db.func.count(Product.id).label('product_count'),
        db.func.sum(Product.stock_quantity).label('total_stock'),
        db.func.sum(Product.cost_price * Product.stock_quantity).label('stock_value'),
        db.func.sum(Product.selling_price * Product.stock_quantity).label('potential_revenue'),
        db.func.avg(Product.selling_price - Product.cost_price).label('avg_profit')
    ).group_by(Product.category).all()
    
    return [
        {
            'category': c.category,
            'product_count': c.product_count,
            'total_stock': c.total_stock or 0,
            'stock_value': c.stock_value or 0,
            'potential_revenue': c.potential_revenue or 0,
            'avg_profit': c.avg_profit or 0
        }
        for c in categories
    ]

# Authentication Middleware
def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        current_user = get_jwt_identity()
        admin = Admin.query.filter_by(username=current_user, is_active=True).first()
        if not admin:
            return jsonify({'error': 'Admin access required'}), 403
        return fn(*args, **kwargs)
    return wrapper

# Routes
@app.route('/')
def home():
    return jsonify({
        'message': 'Karanja Shoe Store Admin API',
        'version': '1.0.0',
        'endpoints': {
            'auth': ['/api/auth/login', '/api/auth/register', '/api/auth/logout'],
            'products': ['/api/products', '/api/products/<id>'],
            'sales': ['/api/sales', '/api/sales/<id>'],
            'analytics': ['/api/analytics/dashboard', '/api/analytics/sales-trends'],
            'customers': ['/api/customers', '/api/customers/<id>']
        }
    })

# Authentication Routes
@app.route('/api/auth/register', methods=['POST'])
def register():
    """Register a new admin (first time setup only)"""
    data = request.get_json()
    
    # Check if any admin exists
    existing_admin = Admin.query.first()
    if existing_admin:
        return jsonify({'error': 'Admin already registered'}), 400
    
    # Validate input
    required_fields = ['username', 'email', 'password', 'full_name']
    for field in required_fields:
        if not data.get(field):
            return jsonify({'error': f'{field} is required'}), 400
    
    # Create admin
    admin = Admin(
        username=data['username'],
        email=data['email'],
        full_name=data['full_name'],
        phone=data.get('phone')
    )
    admin.set_password(data['password'])
    
    db.session.add(admin)
    db.session.commit()
    
    return jsonify({
        'message': 'Admin registered successfully',
        'admin': admin.to_dict()
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Admin login"""
    data = request.get_json()
    
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    
    # Find admin
    admin = Admin.query.filter_by(username=username, is_active=True).first()
    if not admin or not admin.check_password(password):
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # Update last login
    admin.last_login = datetime.utcnow()
    db.session.commit()
    
    # Create access token
    access_token = create_access_token(identity=username)
    
    return jsonify({
        'message': 'Login successful',
        'access_token': access_token,
        'admin': admin.to_dict()
    })

@app.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """Admin logout (client-side token disposal)"""
    return jsonify({'message': 'Logout successful'})

@app.route('/api/auth/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get admin profile"""
    username = get_jwt_identity()
    admin = Admin.query.filter_by(username=username, is_active=True).first()
    
    if not admin:
        return jsonify({'error': 'Admin not found'}), 404
    
    return jsonify({'admin': admin.to_dict()})

@app.route('/api/auth/profile', methods=['PUT'])
@jwt_required()
def update_profile():
    """Update admin profile"""
    username = get_jwt_identity()
    admin = Admin.query.filter_by(username=username, is_active=True).first()
    
    if not admin:
        return jsonify({'error': 'Admin not found'}), 404
    
    data = request.get_json()
    
    # Update fields
    if 'email' in data:
        admin.email = data['email']
    if 'full_name' in data:
        admin.full_name = data['full_name']
    if 'phone' in data:
        admin.phone = data['phone']
    
    # Update password if provided
    if 'password' in data and 'old_password' in data:
        if admin.check_password(data['old_password']):
            admin.set_password(data['password'])
        else:
            return jsonify({'error': 'Old password is incorrect'}), 400
    
    db.session.commit()
    
    return jsonify({
        'message': 'Profile updated successfully',
        'admin': admin.to_dict()
    })

# Product Management Routes
@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products with filters"""
    # Get query parameters
    category = request.args.get('category')
    search = request.args.get('search')
    low_stock = request.args.get('low_stock', 'false').lower() == 'true'
    out_of_stock = request.args.get('out_of_stock', 'false').lower() == 'true'
    
    # Build query
    query = Product.query
    
    if category:
        query = query.filter_by(category=category)
    
    if search:
        query = query.filter(
            (Product.name.ilike(f'%{search}%')) |
            (Product.sku.ilike(f'%{search}%')) |
            (Product.description.ilike(f'%{search}%'))
        )
    
    if low_stock:
        query = query.filter(Product.stock_quantity <= Product.reorder_level)
    
    if out_of_stock:
        query = query.filter_by(stock_quantity=0)
    
    products = query.order_by(Product.created_at.desc()).all()
    
    return jsonify({
        'products': [p.to_dict() for p in products],
        'count': len(products)
    })

@app.route('/api/products/<int:product_id>', methods=['GET'])
@jwt_required()
def get_product(product_id):
    """Get single product"""
    product = Product.query.get_or_404(product_id)
    return jsonify({'product': product.to_dict()})

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
    try:
        data = request.form.to_dict()
        files = request.files
        
        # Validate required fields
        required_fields = ['name', 'category', 'size', 'cost_price', 'selling_price']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        # Generate SKU if not provided
        sku = data.get('sku')
        if not sku:
            sku = generate_sku(data['category'], data['size'])
        
        # Check if SKU already exists
        existing = Product.query.filter_by(sku=sku).first()
        if existing:
            return jsonify({'error': 'SKU already exists'}), 400
        
        # Handle image upload
        image_url = None
        image_path = None
        if 'image' in files:
            file = files['image']
            image_url, image_path = save_product_image(file)
        
        # Create product
        product = Product(
            sku=sku,
            name=data['name'],
            description=data.get('description'),
            category=data['category'],
            size=data['size'],
            color=data.get('color'),
            material=data.get('material'),
            cost_price=float(data['cost_price']),
            selling_price=float(data['selling_price']),
            stock_quantity=int(data.get('stock_quantity', 0)),
            reorder_level=int(data.get('reorder_level', 5)),
            initial_stock=int(data.get('stock_quantity', 0)),
            image_url=image_url,
            image_path=image_path
        )
        
        db.session.add(product)
        db.session.commit()
        
        # Check for stock alert
        if product.stock_quantity <= product.reorder_level:
            alert = StockAlert(
                product_id=product.id,
                alert_type='low_stock' if product.stock_quantity > 0 else 'out_of_stock',
                current_stock=product.stock_quantity,
                threshold=product.reorder_level
            )
            db.session.add(alert)
            db.session.commit()
        
        return jsonify({
            'message': 'Product created successfully',
            'product': product.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update product"""
    try:
        product = Product.query.get_or_404(product_id)
        data = request.form.to_dict()
        files = request.files
        
        # Update fields
        if 'name' in data:
            product.name = data['name']
        if 'description' in data:
            product.description = data['description']
        if 'category' in data:
            product.category = data['category']
        if 'size' in data:
            product.size = data['size']
        if 'color' in data:
            product.color = data['color']
        if 'material' in data:
            product.material = data['material']
        if 'cost_price' in data:
            product.cost_price = float(data['cost_price'])
        if 'selling_price' in data:
            product.selling_price = float(data['selling_price'])
        if 'stock_quantity' in data:
            product.stock_quantity = int(data['stock_quantity'])
        if 'reorder_level' in data:
            product.reorder_level = int(data['reorder_level'])
        if 'is_active' in data:
            product.is_active = data['is_active'].lower() == 'true'
        
        # Handle image upload
        if 'image' in files:
            file = files['image']
            image_url, image_path = save_product_image(file)
            if image_url:
                product.image_url = image_url
                product.image_path = image_path
        
        product.updated_at = datetime.utcnow()
        
        # Check for stock alert
        if product.stock_quantity <= product.reorder_level:
            # Check if alert already exists
            existing_alert = StockAlert.query.filter_by(
                product_id=product.id,
                is_resolved=False
            ).first()
            
            if not existing_alert:
                alert = StockAlert(
                    product_id=product.id,
                    alert_type='low_stock' if product.stock_quantity > 0 else 'out_of_stock',
                    current_stock=product.stock_quantity,
                    threshold=product.reorder_level
                )
                db.session.add(alert)
        
        db.session.commit()
        
        return jsonify({
            'message': 'Product updated successfully',
            'product': product.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    try:
        product = Product.query.get_or_404(product_id)
        
        # Check if product has sales
        if product.sales:
            return jsonify({
                'error': 'Cannot delete product with sales history. Deactivate instead.'
            }), 400
        
        # Delete image file if exists
        if product.image_path and os.path.exists(product.image_path):
            os.remove(product.image_path)
        
        # Delete stock alerts
        StockAlert.query.filter_by(product_id=product_id).delete()
        
        db.session.delete(product)
        db.session.commit()
        
        return jsonify({'message': 'Product deleted successfully'})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/import', methods=['POST'])
@jwt_required()
def import_products():
    """Import products from CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be CSV'}), 400
        
        # Read CSV
        df = pd.read_csv(file)
        
        # Validate columns
        required_columns = ['name', 'category', 'size', 'cost_price', 'selling_price', 'stock_quantity']
        for col in required_columns:
            if col not in df.columns:
                return jsonify({'error': f'Missing required column: {col}'}), 400
        
        imported = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Generate SKU
                sku = generate_sku(row['category'], str(row['size']))
                
                # Check if SKU exists
                existing = Product.query.filter_by(sku=sku).first()
                if existing:
                    errors.append(f"Row {index + 1}: SKU {sku} already exists")
                    continue
                
                # Create product
                product = Product(
                    sku=sku,
                    name=str(row['name']),
                    description=str(row.get('description', '')),
                    category=str(row['category']),
                    size=str(row['size']),
                    color=str(row.get('color', '')),
                    material=str(row.get('material', '')),
                    cost_price=float(row['cost_price']),
                    selling_price=float(row['selling_price']),
                    stock_quantity=int(row['stock_quantity']),
                    reorder_level=int(row.get('reorder_level', 5)),
                    initial_stock=int(row['stock_quantity'])
                )
                
                db.session.add(product)
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {index + 1}: {str(e)}")
        
        db.session.commit()
        
        return jsonify({
            'message': f'Imported {imported} products successfully',
            'imported_count': imported,
            'errors': errors
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/export', methods=['GET'])
@jwt_required()
def export_products():
    """Export products to CSV"""
    try:
        products = Product.query.all()
        
        # Create DataFrame
        data = []
        for p in products:
            data.append({
                'sku': p.sku,
                'name': p.name,
                'category': p.category,
                'size': p.size,
                'color': p.color,
                'material': p.material,
                'cost_price': p.cost_price,
                'selling_price': p.selling_price,
                'stock_quantity': p.stock_quantity,
                'reorder_level': p.reorder_level,
                'description': p.description,
                'is_active': p.is_active,
                'created_at': p.created_at,
                'updated_at': p.updated_at
            })
        
        df = pd.DataFrame(data)
        
        # Create CSV in memory
        csv_data = df.to_csv(index=False)
        
        # Create response
        response = app.response_class(
            response=csv_data,
            status=200,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=products_export.csv'}
        )
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Sales Management Routes
@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales with filters"""
    # Get query parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    product_id = request.args.get('product_id')
    payment_method = request.args.get('payment_method')
    
    # Build query
    query = Sale.query
    
    if start_date:
        query = query.filter(Sale.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(Sale.created_at <= datetime.fromisoformat(end_date))
    if product_id:
        query = query.filter_by(product_id=int(product_id))
    if payment_method:
        query = query.filter_by(payment_method=payment_method)
    
    sales = query.order_by(Sale.created_at.desc()).all()
    
    return jsonify({
        'sales': [s.to_dict() for s in sales],
        'count': len(sales)
    })

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Create new sale (record transaction)"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['product_id', 'quantity', 'customer_name', 'customer_phone', 'payment_method']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        product = Product.query.get(data['product_id'])
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock availability
        if product.stock_quantity < data['quantity']:
            return jsonify({'error': 'Insufficient stock'}), 400
        
        # Calculate amounts
        unit_price = product.selling_price
        total_amount = unit_price * data['quantity']
        profit = (unit_price - product.cost_price) * data['quantity']
        
        # Generate transaction ID
        transaction_id = f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.randbelow(1000):03d}"
        
        # Create sale
        sale = Sale(
            transaction_id=transaction_id,
            product_id=data['product_id'],
            quantity=data['quantity'],
            unit_price=unit_price,
            total_amount=total_amount,
            profit=profit,
            payment_method=data['payment_method'],
            mpesa_receipt=data.get('mpesa_receipt'),
            customer_name=data['customer_name'],
            customer_phone=data['customer_phone'],
            notes=data.get('notes')
        )
        
        # Update product stock
        product.stock_quantity -= data['quantity']
        
        # Update or create customer
        customer = Customer.query.filter_by(phone=data['customer_phone']).first()
        if not customer:
            customer = Customer(
                customer_id=f"CUST{secrets.randbelow(10000):04d}",
                full_name=data['customer_name'],
                phone=data['customer_phone'],
                email=data.get('customer_email')
            )
            db.session.add(customer)
        
        # Update customer stats
        customer.total_orders += 1
        customer.total_spent += total_amount
        customer.last_purchase = datetime.utcnow()
        
        db.session.add(sale)
        db.session.commit()
        
        return jsonify({
            'message': 'Sale recorded successfully',
            'sale': sale.to_dict(),
            'receipt': {
                'transaction_id': transaction_id,
                'customer_name': data['customer_name'],
                'product_name': product.name,
                'quantity': data['quantity'],
                'unit_price': unit_price,
                'total_amount': total_amount,
                'payment_method': data['payment_method'],
                'date': sale.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/<int:sale_id>', methods=['DELETE'])
@jwt_required()
def cancel_sale(sale_id):
    """Cancel/void a sale"""
    try:
        sale = Sale.query.get_or_404(sale_id)
        
        if sale.status == 'cancelled':
            return jsonify({'error': 'Sale already cancelled'}), 400
        
        # Restore product stock
        product = Product.query.get(sale.product_id)
        if product:
            product.stock_quantity += sale.quantity
        
        # Update customer stats
        customer = Customer.query.filter_by(phone=sale.customer_phone).first()
        if customer:
            customer.total_orders = max(0, customer.total_orders - 1)
            customer.total_spent = max(0, customer.total_spent - sale.total_amount)
        
        # Mark sale as cancelled
        sale.status = 'cancelled'
        
        db.session.commit()
        
        return jsonify({
            'message': 'Sale cancelled successfully',
            'sale': sale.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Analytics Routes
@app.route('/api/analytics/dashboard', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    stats = calculate_dashboard_stats()
    
    # Get recent sales (last 10)
    recent_sales = Sale.query.order_by(Sale.created_at.desc()).limit(10).all()
    
    # Get low stock alerts
    low_stock_alerts = StockAlert.query.filter_by(is_resolved=False).all()
    
    # Get top selling products
    top_products = db.session.query(
        Product,
        db.func.sum(Sale.quantity).label('total_sold'),
        db.func.sum(Sale.total_amount).label('total_revenue'),
        db.func.sum(Sale.profit).label('total_profit')
    ).join(Sale).group_by(Product.id).order_by(
        db.func.sum(Sale.quantity).desc()
    ).limit(5).all()
    
    top_products_data = []
    for product, total_sold, total_revenue, total_profit in top_products:
        top_products_data.append({
            'product': product.to_dict(),
            'total_sold': total_sold or 0,
            'total_revenue': total_revenue or 0,
            'total_profit': total_profit or 0
        })
    
    return jsonify({
        'stats': stats,
        'recent_sales': [s.to_dict() for s in recent_sales],
        'low_stock_alerts': [a.to_dict() for a in low_stock_alerts],
        'top_products': top_products_data,
        'category_analysis': get_category_analysis()
    })

@app.route('/api/analytics/sales-trends', methods=['GET'])
@jwt_required()
def get_sales_trends():
    """Get sales trends data"""
    days = int(request.args.get('days', 30))
    trends = get_sales_trends(days)
    return jsonify(trends)

@app.route('/api/analytics/financial-report', methods=['GET'])
@jwt_required()
def get_financial_report():
    """Get financial report"""
    # Date range
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    if start_date_str and end_date_str:
        start_date = datetime.fromisoformat(start_date_str)
        end_date = datetime.fromisoformat(end_date_str)
    else:
        # Default to current month
        today = datetime.utcnow()
        start_date = today.replace(day=1)
        end_date = today
    
    # Sales in period
    sales = Sale.query.filter(
        Sale.created_at >= start_date,
        Sale.created_at <= end_date
    ).all()
    
    total_revenue = sum(s.total_amount for s in sales)
    total_profit = sum(s.profit for s in sales)
    total_sales = len(sales)
    
    # By payment method
    payment_methods = {}
    for sale in sales:
        method = sale.payment_method or 'unknown'
        payment_methods[method] = payment_methods.get(method, 0) + sale.total_amount
    
    # By category
    category_sales = db.session.query(
        Product.category,
        db.func.sum(Sale.quantity).label('quantity'),
        db.func.sum(Sale.total_amount).label('revenue'),
        db.func.sum(Sale.profit).label('profit')
    ).join(Sale).filter(
        Sale.created_at >= start_date,
        Sale.created_at <= end_date
    ).group_by(Product.category).all()
    
    category_data = []
    for category, quantity, revenue, profit in category_sales:
        category_data.append({
            'category': category,
            'quantity': quantity or 0,
            'revenue': revenue or 0,
            'profit': profit or 0
        })
    
    return jsonify({
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        },
        'summary': {
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'total_sales': total_sales,
            'average_sale_value': total_revenue / total_sales if total_sales > 0 else 0,
            'profit_margin': (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        },
        'payment_methods': payment_methods,
        'categories': category_data
    })

@app.route('/api/analytics/stock-report', methods=['GET'])
@jwt_required()
def get_stock_report():
    """Get stock analysis report"""
    products = Product.query.all()
    
    # Calculate stock metrics
    total_stock_value = sum(p.cost_price * p.stock_quantity for p in products)
    total_potential_revenue = sum(p.selling_price * p.stock_quantity for p in products)
    total_profit_potential = total_potential_revenue - total_stock_value
    
    # Low stock items
    low_stock_items = [p.to_dict() for p in products if p.stock_quantity <= p.reorder_level and p.stock_quantity > 0]
    out_of_stock_items = [p.to_dict() for p in products if p.stock_quantity == 0]
    
    # Stock turnover (simplified)
    stock_turnover = {}
    for product in products:
        if product.initial_stock > 0:
            turnover = ((product.initial_stock - product.stock_quantity) / product.initial_stock) * 100
            stock_turnover[product.id] = {
                'product_name': product.name,
                'turnover_rate': round(turnover, 2),
                'initial_stock': product.initial_stock,
                'current_stock': product.stock_quantity,
                'sold': product.initial_stock - product.stock_quantity
            }
    
    return jsonify({
        'stock_summary': {
            'total_products': len(products),
            'total_stock_quantity': sum(p.stock_quantity for p in products),
            'total_stock_value': total_stock_value,
            'total_potential_revenue': total_potential_revenue,
            'total_profit_potential': total_profit_potential,
            'average_profit_margin': (total_profit_potential / total_stock_value * 100) if total_stock_value > 0 else 0
        },
        'low_stock_items': low_stock_items,
        'out_of_stock_items': out_of_stock_items,
        'stock_turnover': list(stock_turnover.values()),
        'category_breakdown': get_category_analysis()
    })

# Customer Management Routes
@app.route('/api/customers', methods=['GET'])
@jwt_required()
def get_customers():
    """Get all customers"""
    search = request.args.get('search')
    
    query = Customer.query
    
    if search:
        query = query.filter(
            (Customer.full_name.ilike(f'%{search}%')) |
            (Customer.phone.ilike(f'%{search}%')) |
            (Customer.email.ilike(f'%{search}%'))
        )
    
    customers = query.order_by(Customer.created_at.desc()).all()
    
    return jsonify({
        'customers': [c.to_dict() for c in customers],
        'count': len(customers)
    })

@app.route('/api/customers/<int:customer_id>', methods=['GET'])
@jwt_required()
def get_customer(customer_id):
    """Get single customer with purchase history"""
    customer = Customer.query.get_or_404(customer_id)
    
    # Get customer's purchase history
    sales = Sale.query.filter_by(customer_phone=customer.phone).order_by(Sale.created_at.desc()).all()
    
    return jsonify({
        'customer': customer.to_dict(),
        'purchase_history': [s.to_dict() for s in sales],
        'total_purchases': len(sales),
        'average_purchase_value': customer.total_spent / customer.total_orders if customer.total_orders > 0 else 0
    })

@app.route('/api/customers/<int:customer_id>', methods=['PUT'])
@jwt_required()
def update_customer(customer_id):
    """Update customer information"""
    try:
        customer = Customer.query.get_or_404(customer_id)
        data = request.get_json()
        
        if 'full_name' in data:
            customer.full_name = data['full_name']
        if 'email' in data:
            customer.email = data['email']
        if 'address' in data:
            customer.address = data['address']
        if 'phone' in data:
            # Check if new phone already exists
            if data['phone'] != customer.phone:
                existing = Customer.query.filter_by(phone=data['phone']).first()
                if existing:
                    return jsonify({'error': 'Phone number already registered'}), 400
            customer.phone = data['phone']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Customer updated successfully',
            'customer': customer.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Stock Alert Routes
@app.route('/api/alerts', methods=['GET'])
@jwt_required()
def get_alerts():
    """Get all stock alerts"""
    resolved = request.args.get('resolved', 'false').lower() == 'true'
    
    query = StockAlert.query
    
    if not resolved:
        query = query.filter_by(is_resolved=False)
    
    alerts = query.order_by(StockAlert.created_at.desc()).all()
    
    return jsonify({
        'alerts': [a.to_dict() for a in alerts],
        'count': len(alerts)
    })

@app.route('/api/alerts/<int:alert_id>/resolve', methods=['PUT'])
@jwt_required()
def resolve_alert(alert_id):
    """Mark alert as resolved"""
    try:
        alert = StockAlert.query.get_or_404(alert_id)
        
        if alert.is_resolved:
            return jsonify({'error': 'Alert already resolved'}), 400
        
        alert.is_resolved = True
        alert.resolved_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Alert resolved successfully',
            'alert': alert.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# File Serving Route
@app.route('/static/uploads/products/<filename>')
def serve_product_image(filename):
    """Serve product images"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Error Handlers
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 16MB.'}), 413

# Initialize Database
def init_db():
    """Initialize database with admin if not exists"""
    with app.app_context():
        db.create_all()
        
        # Create default admin if none exists
        if not Admin.query.first():
            admin = Admin(
                username='admin',
                email='admin@karanjashoestore.co.ke',
                full_name='Admin Karanja',
                phone='+254700000000'
            )
            admin.set_password('admin123')  # Change this in production!
            db.session.add(admin)
            db.session.commit()
            print("Default admin created: username='admin', password='admin123'")

# Run the application
if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
