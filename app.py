"""
KARANJA SHOE STORE - COMPLETE ADMIN BACKEND
Production-ready with authentication, product management, sales tracking,
financial analytics, and stock management.
"""

import os
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
import base64
from io import BytesIO
import hashlib
import csv
from typing import Dict, List, Any, Optional
import traceback

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

# ==================== INITIALIZATION ====================
app = Flask(__name__)
CORS(app, supports_credentials=True)

# ==================== CONFIGURATION ====================
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', secrets.token_hex(32)),
    DATABASE=os.path.join(os.path.dirname(__file__), 'instance', 'karanja.db'),
    UPLOAD_FOLDER=os.path.join(os.path.dirname(__file__), 'static', 'uploads'),
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10MB
    JSON_SORT_KEYS=False,
    JSON_AS_ASCII=False
)

# Create necessary directories
os.makedirs(os.path.dirname(app.config['DATABASE']), exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ==================== DATABASE SETUP ====================
def get_db_connection():
    """Get SQLite database connection with proper configuration"""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_database():
    """Initialize database with all required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tables
    tables = [
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            role TEXT DEFAULT 'admin',
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            last_password_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            category_id INTEGER NOT NULL,
            category_name TEXT NOT NULL,
            size TEXT NOT NULL,
            color TEXT,
            material TEXT,
            brand TEXT,
            
            cost_price DECIMAL(10, 2) NOT NULL,
            selling_price DECIMAL(10, 2) NOT NULL,
            discount_price DECIMAL(10, 2) DEFAULT 0,
            
            stock_quantity INTEGER DEFAULT 0,
            initial_stock INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 5,
            min_stock_alert INTEGER DEFAULT 3,
            
            image_url TEXT,
            image_data TEXT,
            
            is_featured BOOLEAN DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (category_id) REFERENCES categories (id),
            FOREIGN KEY (created_by) REFERENCES admin_users (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_code TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT UNIQUE NOT NULL,
            address TEXT,
            city TEXT,
            country TEXT DEFAULT 'Kenya',
            
            total_orders INTEGER DEFAULT 0,
            total_spent DECIMAL(15, 2) DEFAULT 0,
            last_order_date TIMESTAMP,
            first_order_date TIMESTAMP,
            
            loyalty_points INTEGER DEFAULT 0,
            notes TEXT,
            
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT UNIQUE NOT NULL,
            customer_id INTEGER,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            
            total_items INTEGER DEFAULT 0,
            subtotal DECIMAL(15, 2) NOT NULL,
            discount DECIMAL(15, 2) DEFAULT 0,
            tax DECIMAL(15, 2) DEFAULT 0,
            total_amount DECIMAL(15, 2) NOT NULL,
            amount_paid DECIMAL(15, 2) NOT NULL,
            change_amount DECIMAL(15, 2) DEFAULT 0,
            
            payment_method TEXT NOT NULL,
            payment_status TEXT DEFAULT 'completed',
            mpesa_receipt TEXT,
            transaction_id TEXT,
            
            sale_type TEXT DEFAULT 'retail',  -- retail, wholesale, online
            sale_status TEXT DEFAULT 'completed',  -- pending, completed, cancelled, refunded
            
            notes TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (customer_id) REFERENCES customers (id),
            FOREIGN KEY (created_by) REFERENCES admin_users (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS sale_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_sku TEXT NOT NULL,
            
            quantity INTEGER NOT NULL,
            unit_price DECIMAL(10, 2) NOT NULL,
            cost_price DECIMAL(10, 2) NOT NULL,
            discount DECIMAL(10, 2) DEFAULT 0,
            
            subtotal DECIMAL(15, 2) NOT NULL,
            profit DECIMAL(15, 2) NOT NULL,
            
            FOREIGN KEY (sale_id) REFERENCES sales (id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT NOT NULL,  -- purchase, sale, adjustment, return, damage
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_cost DECIMAL(10, 2),
            total_cost DECIMAL(15, 2),
            
            reference_id TEXT,  -- invoice number, purchase order, etc.
            notes TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (created_by) REFERENCES admin_users (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_type TEXT NOT NULL,  -- rent, salary, utilities, transport, supplies, other
            description TEXT NOT NULL,
            amount DECIMAL(15, 2) NOT NULL,
            payment_method TEXT,
            reference_number TEXT,
            
            expense_date DATE NOT NULL,
            paid_to TEXT,
            notes TEXT,
            
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (created_by) REFERENCES admin_users (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS stock_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            alert_type TEXT NOT NULL,  -- low_stock, out_of_stock, expired
            current_quantity INTEGER,
            threshold_quantity INTEGER,
            is_resolved BOOLEAN DEFAULT 0,
            resolved_at TIMESTAMP,
            resolved_by INTEGER,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            FOREIGN KEY (product_id) REFERENCES products (id),
            FOREIGN KEY (resolved_by) REFERENCES admin_users (id)
        )
        """,
        
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            action_type TEXT NOT NULL,  -- login, logout, create, update, delete
            table_name TEXT,
            record_id INTEGER,
            old_values TEXT,
            new_values TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    ]
    
    # Create all tables
    for table_sql in tables:
        cursor.execute(table_sql)
    
    # Insert default categories
    default_categories = [
        ('Official Shoes', 'Formal shoes for office and business'),
        ('Sports Shoes', 'Athletic and sports footwear'),
        ('Casual Shoes', 'Everyday casual footwear'),
        ('Boots', 'Leather boots and work boots'),
        ('Sandals', 'Open footwear for casual wear'),
        ('Sneakers', 'Fashion sneakers and trainers')
    ]
    
    for category in default_categories:
        cursor.execute(
            'INSERT OR IGNORE INTO categories (name, description) VALUES (?, ?)',
            category
        )
    
    # Create default admin if not exists
    cursor.execute('SELECT id FROM admin_users WHERE username = ?', ('admin',))
    if not cursor.fetchone():
        password_hash = hash_password('admin123')
        cursor.execute('''
            INSERT INTO admin_users 
            (username, email, password_hash, full_name, phone, role)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('admin', 'admin@karanjashoestore.co.ke', password_hash, 
              'Administrator', '+254700000000', 'admin'))
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

# ==================== SECURITY & AUTHENTICATION ====================
def hash_password(password: str) -> str:
    """Hash password using SHA-256 with salt"""
    salt = os.environ.get('PASSWORD_SALT', 'karanja_shoe_store_salt')
    return hashlib.sha256((password + salt).encode()).hexdigest()

def verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored hash"""
    return stored_hash == hash_password(password)

def generate_token(user_id: int, username: str) -> str:
    """Generate simple token (in production, use JWT)"""
    token_data = f"{user_id}:{username}:{datetime.now().timestamp()}"
    return base64.b64encode(token_data.encode()).decode()

def verify_token(token: str) -> Optional[Dict]:
    """Verify token and return user data"""
    try:
        token_data = base64.b64decode(token).decode()
        user_id, username, timestamp = token_data.split(':')
        
        # Check if token is expired (24 hours)
        if datetime.now().timestamp() - float(timestamp) > 86400:
            return None
        
        return {'id': int(user_id), 'username': username}
    except:
        return None

def login_required(f):
    """Authentication decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        
        if not token:
            return jsonify({'error': 'Authentication required', 'code': 'AUTH_REQUIRED'}), 401
        
        # Remove 'Bearer ' prefix if present
        if token.startswith('Bearer '):
            token = token[7:]
        
        user = verify_token(token)
        if not user:
            return jsonify({'error': 'Invalid or expired token', 'code': 'INVALID_TOKEN'}), 401
        
        # Add user info to request context
        request.current_user = user
        return f(*args, **kwargs)
    
    return decorated_function

def admin_required(f):
    """Admin-only decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user is authenticated
        if not hasattr(request, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        # In production, check user role from database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT role FROM admin_users WHERE id = ? AND is_active = 1',
            (request.current_user['id'],)
        )
        user = cursor.fetchone()
        conn.close()
        
        if not user or user['role'] != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function

# ==================== UTILITY FUNCTIONS ====================
def log_audit(action_type: str, table_name: str = None, 
              record_id: int = None, old_values: str = None, 
              new_values: str = None):
    """Log audit trail"""
    try:
        user_id = request.current_user['id'] if hasattr(request, 'current_user') else None
        username = request.current_user['username'] if hasattr(request, 'current_user') else None
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO audit_logs 
            (user_id, username, action_type, table_name, record_id, 
             old_values, new_values, ip_address, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id, username, action_type, table_name, record_id,
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None,
            request.remote_addr,
            request.user_agent.string[:500]
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Audit logging failed: {e}")

def generate_sku(category: str, size: str) -> str:
    """Generate unique SKU"""
    category_code = category[:3].upper()
    timestamp = datetime.now().strftime('%y%m%d')
    random_num = secrets.randbelow(1000)
    return f"{category_code}-{size}-{timestamp}-{random_num:03d}"

def generate_invoice_number() -> str:
    """Generate unique invoice number"""
    date_str = datetime.now().strftime('%Y%m%d')
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get today's invoice count
    cursor.execute('''
        SELECT COUNT(*) as count FROM sales 
        WHERE DATE(created_at) = DATE('now')
    ''')
    count = cursor.fetchone()['count'] + 1
    conn.close()
    
    return f"INV-{date_str}-{count:04d}"

def calculate_profit_metrics(products: List) -> List:
    """Calculate profit metrics for products"""
    result = []
    for product in products:
        product_dict = dict(product)
        
        cost = product_dict.get('cost_price', 0) or 0
        sell = product_dict.get('selling_price', 0) or 0
        stock = product_dict.get('stock_quantity', 0) or 0
        
        profit_per_unit = sell - cost
        profit_margin = ((profit_per_unit / cost) * 100) if cost > 0 else 0
        stock_value = cost * stock
        potential_revenue = sell * stock
        total_profit_potential = profit_per_unit * stock
        
        product_dict.update({
            'profit_per_unit': round(profit_per_unit, 2),
            'profit_margin': round(profit_margin, 2),
            'stock_value': round(stock_value, 2),
            'potential_revenue': round(potential_revenue, 2),
            'total_profit_potential': round(total_profit_potential, 2),
            'status': 'In Stock' if stock > 0 else 'Out of Stock',
            'low_stock': stock <= product_dict.get('reorder_level', 5)
        })
        
        result.append(product_dict)
    
    return result

# ==================== AUTHENTICATION ROUTES ====================
@app.route('/api/auth/login', methods=['POST'])
def login():
    """Admin login endpoint"""
    try:
        data = request.get_json()
        
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({'error': 'Username and password required', 'code': 'MISSING_CREDENTIALS'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check user exists and is active
        cursor.execute('''
            SELECT id, username, email, full_name, phone, role, password_hash 
            FROM admin_users 
            WHERE username = ? AND is_active = 1
        ''', (data['username'],))
        
        user = cursor.fetchone()
        
        if not user or not verify_password(user['password_hash'], data['password']):
            conn.close()
            return jsonify({'error': 'Invalid username or password', 'code': 'INVALID_CREDENTIALS'}), 401
        
        # Update last login
        cursor.execute(
            'UPDATE admin_users SET last_login = CURRENT_TIMESTAMP WHERE id = ?',
            (user['id'],)
        )
        
        # Generate token
        token = generate_token(user['id'], user['username'])
        
        # Log audit
        log_audit('login')
        
        conn.commit()
        
        user_data = {
            'id': user['id'],
            'username': user['username'],
            'email': user['email'],
            'full_name': user['full_name'],
            'phone': user['phone'],
            'role': user['role']
        }
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': token,
            'user': user_data
        })
        
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}', 'code': 'LOGIN_FAILED'}), 500

@app.route('/api/auth/logout', methods=['POST'])
@login_required
def logout():
    """Logout endpoint"""
    log_audit('logout')
    return jsonify({'success': True, 'message': 'Logged out successfully'})

@app.route('/api/auth/profile', methods=['GET'])
@login_required
def get_profile():
    """Get current user profile"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, full_name, phone, role, 
                   created_at, last_login
            FROM admin_users 
            WHERE id = ?
        ''', (request.current_user['id'],))
        
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'success': True,
            'user': dict(user)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/change-password', methods=['POST'])
@login_required
def change_password():
    """Change password"""
    try:
        data = request.get_json()
        
        if not data or 'old_password' not in data or 'new_password' not in data:
            return jsonify({'error': 'Old and new password required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get current password hash
        cursor.execute(
            'SELECT password_hash FROM admin_users WHERE id = ?',
            (request.current_user['id'],)
        )
        user = cursor.fetchone()
        
        if not user or not verify_password(user['password_hash'], data['old_password']):
            conn.close()
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        # Update password
        new_hash = hash_password(data['new_password'])
        cursor.execute('''
            UPDATE admin_users 
            SET password_hash = ?, last_password_change = CURRENT_TIMESTAMP 
            WHERE id = ?
        ''', (new_hash, request.current_user['id']))
        
        log_audit('change_password')
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Password changed successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== CATEGORIES ROUTES ====================
@app.route('/api/categories', methods=['GET'])
@login_required
def get_categories():
    """Get all categories"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM categories ORDER BY name')
        categories = [dict(cat) for cat in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'categories': categories,
            'count': len(categories)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCTS ROUTES ====================
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    """Get all products with filters"""
    try:
        # Get query parameters
        category = request.args.get('category')
        search = request.args.get('search')
        low_stock = request.args.get('low_stock', 'false').lower() == 'true'
        out_of_stock = request.args.get('out_of_stock', 'false').lower() == 'true'
        limit = int(request.args.get('limit', 100))
        offset = int(request.args.get('offset', 0))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query
        query = '''
            SELECT p.*, c.name as category_full_name 
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE 1=1
        '''
        params = []
        
        if category:
            query += ' AND p.category_name = ?'
            params.append(category)
        
        if search:
            query += ''' AND (
                p.name LIKE ? OR 
                p.sku LIKE ? OR 
                p.description LIKE ? OR
                p.brand LIKE ?
            )'''
            search_term = f'%{search}%'
            params.extend([search_term, search_term, search_term, search_term])
        
        if low_stock:
            query += ' AND p.stock_quantity <= p.reorder_level AND p.stock_quantity > 0'
        
        if out_of_stock:
            query += ' AND p.stock_quantity = 0'
        
        query += ' ORDER BY p.created_at DESC LIMIT ? OFFSET ?'
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        products = cursor.fetchall()
        
        # Get total count
        count_query = 'SELECT COUNT(*) as total FROM products WHERE 1=1'
        count_params = []
        
        if category:
            count_query += ' AND category_name = ?'
            count_params.append(category)
        
        if search:
            count_query += ''' AND (
                name LIKE ? OR 
                sku LIKE ? OR 
                description LIKE ?
            )'''
            count_params.extend([search_term, search_term, search_term])
        
        cursor.execute(count_query, count_params)
        total = cursor.fetchone()['total']
        
        conn.close()
        
        # Calculate profit metrics
        products_with_metrics = calculate_profit_metrics(products)
        
        return jsonify({
            'success': True,
            'products': products_with_metrics,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + len(products)) < total
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['GET'])
@login_required
def get_product(product_id):
    """Get single product by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT p.*, c.name as category_full_name 
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.id = ?
        ''', (product_id,))
        
        product = cursor.fetchone()
        conn.close()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        # Calculate profit metrics
        product_with_metrics = calculate_profit_metrics([product])[0]
        
        return jsonify({
            'success': True,
            'product': product_with_metrics
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products', methods=['POST'])
@login_required
@admin_required
def create_product():
    """Create new product"""
    try:
        data = request.get_json()
        
        # Validation
        required_fields = ['name', 'category_id', 'category_name', 'size', 
                          'cost_price', 'selling_price']
        
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field.replace("_", " ").title()} is required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Generate SKU
        sku = data.get('sku')
        if not sku:
            sku = generate_sku(data['category_name'], data['size'])
        
        # Check SKU uniqueness
        cursor.execute('SELECT id FROM products WHERE sku = ?', (sku,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'error': f'Product with SKU {sku} already exists'}), 400
        
        # Insert product
        cursor.execute('''
            INSERT INTO products (
                sku, name, description, category_id, category_name,
                size, color, material, brand,
                cost_price, selling_price, discount_price,
                stock_quantity, initial_stock, reorder_level, min_stock_alert,
                image_url, image_data,
                is_featured, is_active, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sku,
            data['name'],
            data.get('description', ''),
            data['category_id'],
            data['category_name'],
            data['size'],
            data.get('color', ''),
            data.get('material', ''),
            data.get('brand', ''),
            float(data['cost_price']),
            float(data['selling_price']),
            float(data.get('discount_price', 0)),
            int(data.get('stock_quantity', 0)),
            int(data.get('stock_quantity', 0)),
            int(data.get('reorder_level', 5)),
            int(data.get('min_stock_alert', 3)),
            data.get('image_url'),
            data.get('image_data'),
            bool(data.get('is_featured', False)),
            bool(data.get('is_active', True)),
            request.current_user['id']
        ))
        
        product_id = cursor.lastrowid
        
        # Create stock transaction
        stock_qty = int(data.get('stock_quantity', 0))
        if stock_qty > 0:
            cursor.execute('''
                INSERT INTO stock_transactions 
                (transaction_type, product_id, product_name, quantity, 
                 unit_cost, total_cost, reference_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'purchase',
                product_id,
                data['name'],
                stock_qty,
                float(data['cost_price']),
                float(data['cost_price']) * stock_qty,
                f'INIT-{sku}',
                request.current_user['id']
            ))
        
        # Check for stock alert
        if stock_qty <= int(data.get('reorder_level', 5)):
            alert_type = 'low_stock' if stock_qty > 0 else 'out_of_stock'
            cursor.execute('''
                INSERT INTO stock_alerts 
                (product_id, product_name, alert_type, current_quantity, threshold_quantity)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                product_id,
                data['name'],
                alert_type,
                stock_qty,
                int(data.get('reorder_level', 5))
            ))
        
        # Log audit
        log_audit('create', 'products', product_id, None, data)
        
        conn.commit()
        
        # Get created product
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        product = dict(cursor.fetchone())
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Product created successfully',
            'product': calculate_profit_metrics([product])[0]
        }), 201
        
    except Exception as e:
        return jsonify({'error': f'Failed to create product: {str(e)}'}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@login_required
@admin_required
def update_product(product_id):
    """Update existing product"""
    try:
        data = request.get_json()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get old product data for audit
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        old_product = cursor.fetchone()
        
        if not old_product:
            conn.close()
            return jsonify({'error': 'Product not found'}), 404
        
        old_product_dict = dict(old_product)
        
        # Build update query
        update_fields = []
        params = []
        
        field_mapping = {
            'name': 'name',
            'description': 'description',
            'category_id': 'category_id',
            'category_name': 'category_name',
            'size': 'size',
            'color': 'color',
            'material': 'material',
            'brand': 'brand',
            'cost_price': 'cost_price',
            'selling_price': 'selling_price',
            'discount_price': 'discount_price',
            'stock_quantity': 'stock_quantity',
            'reorder_level': 'reorder_level',
            'min_stock_alert': 'min_stock_alert',
            'image_url': 'image_url',
            'image_data': 'image_data',
            'is_featured': 'is_featured',
            'is_active': 'is_active'
        }
        
        for key, db_field in field_mapping.items():
            if key in data:
                update_fields.append(f'{db_field} = ?')
                params.append(data[key])
        
        if not update_fields:
            conn.close()
            return jsonify({'error': 'No fields to update'}), 400
        
        # Add updated timestamp
        update_fields.append('updated_at = CURRENT_TIMESTAMP')
        
        # Execute update
        params.append(product_id)
        query = f'UPDATE products SET {", ".join(update_fields)} WHERE id = ?'
        cursor.execute(query, params)
        
        # Handle stock changes
        if 'stock_quantity' in data:
            old_stock = old_product_dict['stock_quantity']
            new_stock = data['stock_quantity']
            
            if new_stock != old_stock:
                diff = new_stock - old_stock
                transaction_type = 'purchase' if diff > 0 else 'adjustment'
                
                cursor.execute('''
                    INSERT INTO stock_transactions 
                    (transaction_type, product_id, product_name, quantity, 
                     unit_cost, total_cost, reference_id, notes, created_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    transaction_type,
                    product_id,
                    old_product_dict['name'],
                    abs(diff),
                    old_product_dict['cost_price'],
                    old_product_dict['cost_price'] * abs(diff),
                    f'ADJ-{old_product_dict["sku"]}',
                    f'Stock adjustment from {old_stock} to {new_stock}',
                    request.current_user['id']
                ))
        
        # Check for stock alert
        if 'stock_quantity' in data or 'reorder_level' in data:
            cursor.execute(
                'SELECT stock_quantity, reorder_level FROM products WHERE id = ?',
                (product_id,)
            )
            product = cursor.fetchone()
            
            if product:
                stock_qty = product['stock_quantity']
                reorder_level = product['reorder_level']
                
                # Check if alert already exists
                cursor.execute('''
                    SELECT id FROM stock_alerts 
                    WHERE product_id = ? AND is_resolved = 0
                ''', (product_id,))
                
                existing_alert = cursor.fetchone()
                
                if stock_qty <= reorder_level and not existing_alert:
                    alert_type = 'low_stock' if stock_qty > 0 else 'out_of_stock'
                    cursor.execute('''
                        INSERT INTO stock_alerts 
                        (product_id, product_name, alert_type, 
                         current_quantity, threshold_quantity)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        product_id,
                        old_product_dict['name'],
                        alert_type,
                        stock_qty,
                        reorder_level
                    ))
        
        # Log audit
        log_audit('update', 'products', product_id, old_product_dict, data)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully'
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to update product: {str(e)}'}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_product(product_id):
    """Delete product (soft delete by setting inactive)"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if product exists
        cursor.execute('SELECT * FROM products WHERE id = ?', (product_id,))
        product = cursor.fetchone()
        
        if not product:
            conn.close()
            return jsonify({'error': 'Product not found'}), 404
        
        # Check if product has sales
        cursor.execute(
            'SELECT COUNT(*) as count FROM sale_items WHERE product_id = ?',
            (product_id,)
        )
        sales_count = cursor.fetchone()['count']
        
        if sales_count > 0:
            # Soft delete (set inactive)
            cursor.execute(
                'UPDATE products SET is_active = 0 WHERE id = ?',
                (product_id,)
            )
            message = 'Product deactivated (has sales history)'
        else:
            # Hard delete
            cursor.execute('DELETE FROM products WHERE id = ?', (product_id,))
            cursor.execute('DELETE FROM stock_alerts WHERE product_id = ?', (product_id,))
            message = 'Product deleted successfully'
        
        # Log audit
        log_audit('delete', 'products', product_id, dict(product), None)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': message
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to delete product: {str(e)}'}), 500

@app.route('/api/products/import', methods=['POST'])
@login_required
@admin_required
def import_products():
    """Import products from CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'Only CSV files are allowed'}), 400
        
        # Read CSV
        stream = file.stream.read().decode("UTF-8")
        csv_data = csv.reader(stream.splitlines())
        
        # Skip header
        headers = next(csv_data)
        
        # Expected columns
        expected_columns = ['name', 'category_name', 'size', 'cost_price', 
                          'selling_price', 'stock_quantity']
        
        for col in expected_columns:
            if col not in headers:
                return jsonify({'error': f'Missing column: {col}'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        imported = 0
        errors = []
        
        for i, row in enumerate(csv_data, 2):  # Start from line 2
            try:
                # Map row to dict
                row_dict = {headers[j]: row[j] for j in range(len(headers))}
                
                # Get category ID
                cursor.execute(
                    'SELECT id FROM categories WHERE name = ?',
                    (row_dict['category_name'],)
                )
                category = cursor.fetchone()
                
                if not category:
                    errors.append(f"Line {i}: Category '{row_dict['category_name']}' not found")
                    continue
                
                # Generate SKU
                sku = generate_sku(row_dict['category_name'], row_dict['size'])
                
                # Check SKU uniqueness
                cursor.execute('SELECT id FROM products WHERE sku = ?', (sku,))
                if cursor.fetchone():
                    sku = f"{sku}-{secrets.randbelow(100)}"
                
                # Insert product
                cursor.execute('''
                    INSERT INTO products (
                        sku, name, description, category_id, category_name,
                        size, color, material, brand,
                        cost_price, selling_price,
                        stock_quantity, initial_stock, reorder_level,
                        created_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    sku,
                    row_dict['name'],
                    row_dict.get('description', ''),
                    category['id'],
                    row_dict['category_name'],
                    row_dict['size'],
                    row_dict.get('color', ''),
                    row_dict.get('material', ''),
                    row_dict.get('brand', ''),
                    float(row_dict['cost_price']),
                    float(row_dict['selling_price']),
                    int(row_dict.get('stock_quantity', 0)),
                    int(row_dict.get('stock_quantity', 0)),
                    int(row_dict.get('reorder_level', 5)),
                    request.current_user['id']
                ))
                
                imported += 1
                
            except Exception as e:
                errors.append(f"Line {i}: {str(e)}")
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Imported {imported} products successfully',
            'imported': imported,
            'errors': errors
        })
        
    except Exception as e:
        return jsonify({'error': f'Import failed: {str(e)}'}), 500

@app.route('/api/products/export', methods=['GET'])
@login_required
def export_products():
    """Export products to CSV"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                sku, name, description, category_name, size,
                color, material, brand, cost_price, selling_price,
                stock_quantity, reorder_level, is_active,
                created_at, updated_at
            FROM products
            ORDER BY created_at DESC
        ''')
        
        products = cursor.fetchall()
        conn.close()
        
        # Create CSV in memory
        output = BytesIO()
        writer = csv.writer(output)
        
        # Write headers
        headers = ['SKU', 'Name', 'Description', 'Category', 'Size', 
                  'Color', 'Material', 'Brand', 'Cost Price', 'Selling Price',
                  'Stock Quantity', 'Reorder Level', 'Status', 
                  'Created At', 'Updated At']
        writer.writerow(headers)
        
        # Write data
        for product in products:
            writer.writerow([
                product['sku'],
                product['name'],
                product['description'] or '',
                product['category_name'],
                product['size'],
                product['color'] or '',
                product['material'] or '',
                product['brand'] or '',
                product['cost_price'],
                product['selling_price'],
                product['stock_quantity'],
                product['reorder_level'],
                'Active' if product['is_active'] else 'Inactive',
                product['created_at'],
                product['updated_at']
            ])
        
        output.seek(0)
        
        # Create response
        response = Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=products_export.csv',
                'Content-Type': 'text/csv; charset=utf-8'
            }
        )
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Export failed: {str(e)}'}), 500

# ==================== SALES ROUTES ====================
@app.route('/api/sales', methods=['POST'])
@login_required
def create_sale():
    """Create new sale"""
    try:
        data = request.get_json()
        
        # Validation
        if 'items' not in data or not data['items']:
            return jsonify({'error': 'Sale items are required'}), 400
        
        if 'payment_method' not in data:
            return jsonify({'error': 'Payment method is required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Generate invoice number
        invoice_number = generate_invoice_number()
        
        # Calculate totals
        subtotal = 0
        total_items = 0
        total_profit = 0
        
        # Validate and process each item
        sale_items = []
        for item in data['items']:
            # Get product details
            cursor.execute('''
                SELECT id, name, sku, cost_price, selling_price, stock_quantity
                FROM products 
                WHERE id = ? AND is_active = 1
            ''', (item['product_id'],))
            
            product = cursor.fetchone()
            
            if not product:
                conn.close()
                return jsonify({'error': f"Product ID {item['product_id']} not found"}), 400
            
            # Check stock
            if product['stock_quantity'] < item['quantity']:
                conn.close()
                return jsonify({
                    'error': f"Insufficient stock for {product['name']}. Available: {product['stock_quantity']}"
                }), 400
            
            # Calculate item totals
            unit_price = float(item.get('unit_price', product['selling_price']))
            cost_price = product['cost_price']
            quantity = item['quantity']
            
            item_subtotal = unit_price * quantity
            item_profit = (unit_price - cost_price) * quantity
            
            subtotal += item_subtotal
            total_items += quantity
            total_profit += item_profit
            
            # Add to sale items list
            sale_items.append({
                'product_id': product['id'],
                'product_name': product['name'],
                'product_sku': product['sku'],
                'quantity': quantity,
                'unit_price': unit_price,
                'cost_price': cost_price,
                'subtotal': item_subtotal,
                'profit': item_profit
            })
        
        # Calculate final totals
        discount = float(data.get('discount', 0))
        tax = float(data.get('tax', 0))
        total_amount = subtotal - discount + tax
        amount_paid = float(data.get('amount_paid', total_amount))
        change_amount = amount_paid - total_amount if amount_paid > total_amount else 0
        
        # Customer handling
        customer_id = None
        customer_name = data.get('customer_name', 'Walk-in Customer')
        customer_phone = data.get('customer_phone', 'N/A')
        
        if customer_phone and customer_phone != 'N/A':
            # Check if customer exists
            cursor.execute(
                'SELECT id FROM customers WHERE phone = ?',
                (customer_phone,)
            )
            customer = cursor.fetchone()
            
            if customer:
                customer_id = customer['id']
                # Update customer stats
                cursor.execute('''
                    UPDATE customers 
                    SET total_orders = total_orders + 1,
                        total_spent = total_spent + ?,
                        last_order_date = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (total_amount, customer_id))
            else:
                # Create new customer
                customer_code = f"CUST{secrets.randbelow(10000):04d}"
                cursor.execute('''
                    INSERT INTO customers 
                    (customer_code, full_name, phone, email, address,
                     total_orders, total_spent, first_order_date, last_order_date)
                    VALUES (?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (
                    customer_code,
                    customer_name,
                    customer_phone,
                    data.get('customer_email'),
                    data.get('customer_address'),
                    total_amount
                ))
                customer_id = cursor.lastrowid
        else:
            # Walk-in customer
            customer_name = 'Walk-in Customer'
            customer_phone = 'N/A'
        
        # Create sale record
        cursor.execute('''
            INSERT INTO sales (
                invoice_number, customer_id, customer_name, customer_phone,
                total_items, subtotal, discount, tax, total_amount,
                amount_paid, change_amount, payment_method, payment_status,
                mpesa_receipt, transaction_id, sale_type, sale_status,
                notes, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            invoice_number,
            customer_id,
            customer_name,
            customer_phone,
            total_items,
            subtotal,
            discount,
            tax,
            total_amount,
            amount_paid,
            change_amount,
            data['payment_method'],
            data.get('payment_status', 'completed'),
            data.get('mpesa_receipt'),
            data.get('transaction_id'),
            data.get('sale_type', 'retail'),
            data.get('sale_status', 'completed'),
            data.get('notes', ''),
            request.current_user['id']
        ))
        
        sale_id = cursor.lastrowid
        
        # Create sale items and update stock
        for item in sale_items:
            # Create sale item
            cursor.execute('''
                INSERT INTO sale_items 
                (sale_id, product_id, product_name, product_sku,
                 quantity, unit_price, cost_price, discount, subtotal, profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                sale_id,
                item['product_id'],
                item['product_name'],
                item['product_sku'],
                item['quantity'],
                item['unit_price'],
                item['cost_price'],
                0,  # item discount
                item['subtotal'],
                item['profit']
            ))
            
            # Update product stock
            cursor.execute('''
                UPDATE products 
                SET stock_quantity = stock_quantity - ?
                WHERE id = ?
            ''', (item['quantity'], item['product_id']))
            
            # Create stock transaction
            cursor.execute('''
                INSERT INTO stock_transactions 
                (transaction_type, product_id, product_name, quantity,
                 unit_cost, total_cost, reference_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                'sale',
                item['product_id'],
                item['product_name'],
                item['quantity'],
                item['cost_price'],
                item['cost_price'] * item['quantity'],
                invoice_number,
                request.current_user['id']
            ))
            
            # Check for stock alert
            cursor.execute('''
                SELECT stock_quantity, reorder_level FROM products WHERE id = ?
            ''', (item['product_id'],))
            
            product = cursor.fetchone()
            if product and product['stock_quantity'] <= product['reorder_level']:
                # Check if alert already exists
                cursor.execute('''
                    SELECT id FROM stock_alerts 
                    WHERE product_id = ? AND is_resolved = 0
                ''', (item['product_id'],))
                
                if not cursor.fetchone():
                    alert_type = 'low_stock' if product['stock_quantity'] > 0 else 'out_of_stock'
                    cursor.execute('''
                        INSERT INTO stock_alerts 
                        (product_id, product_name, alert_type, 
                         current_quantity, threshold_quantity)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (
                        item['product_id'],
                        item['product_name'],
                        alert_type,
                        product['stock_quantity'],
                        product['reorder_level']
                    ))
        
        # Log audit
        log_audit('create', 'sales', sale_id, None, {
            'invoice_number': invoice_number,
            'total_amount': total_amount,
            'customer_name': customer_name
        })
        
        conn.commit()
        
        # Get created sale
        cursor.execute('''
            SELECT s.*, 
                   GROUP_CONCAT(si.product_name) as product_names
            FROM sales s
            LEFT JOIN sale_items si ON s.id = si.sale_id
            WHERE s.id = ?
            GROUP BY s.id
        ''', (sale_id,))
        
        sale = dict(cursor.fetchone())
        
        # Get sale items
        cursor.execute('SELECT * FROM sale_items WHERE sale_id = ?', (sale_id,))
        sale['items'] = [dict(item) for item in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Sale recorded successfully',
            'invoice_number': invoice_number,
            'sale': sale,
            'receipt': {
                'invoice_number': invoice_number,
                'date': sale['created_at'],
                'customer': customer_name,
                'items': sale['items'],
                'subtotal': subtotal,
                'discount': discount,
                'tax': tax,
                'total': total_amount,
                'paid': amount_paid,
                'change': change_amount,
                'payment_method': data['payment_method']
            }
        }), 201
        
    except Exception as e:
        return jsonify({'error': f'Failed to create sale: {str(e)}'}), 500

@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    """Get all sales with filters"""
    try:
        # Get query parameters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        customer_phone = request.args.get('customer_phone')
        payment_method = request.args.get('payment_method')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query
        query = '''
            SELECT s.*, 
                   COUNT(si.id) as item_count,
                   SUM(si.subtotal) as items_subtotal
            FROM sales s
            LEFT JOIN sale_items si ON s.id = si.sale_id
            WHERE 1=1
        '''
        params = []
        
        if start_date:
            query += ' AND DATE(s.created_at) >= DATE(?)'
            params.append(start_date)
        
        if end_date:
            query += ' AND DATE(s.created_at) <= DATE(?)'
            params.append(end_date)
        
        if customer_phone and customer_phone != 'N/A':
            query += ' AND s.customer_phone = ?'
            params.append(customer_phone)
        
        if payment_method:
            query += ' AND s.payment_method = ?'
            params.append(payment_method)
        
        query += ''' 
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        sales = [dict(sale) for sale in cursor.fetchall()]
        
        # Get total count
        count_query = 'SELECT COUNT(*) as total FROM sales WHERE 1=1'
        count_params = []
        
        if start_date:
            count_query += ' AND DATE(created_at) >= DATE(?)'
            count_params.append(start_date)
        
        if end_date:
            count_query += ' AND DATE(created_at) <= DATE(?)'
            count_params.append(end_date)
        
        cursor.execute(count_query, count_params)
        total = cursor.fetchone()['total']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'sales': sales,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + len(sales)) < total
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/<int:sale_id>', methods=['GET'])
@login_required
def get_sale_details(sale_id):
    """Get sale details with items"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get sale
        cursor.execute('SELECT * FROM sales WHERE id = ?', (sale_id,))
        sale = cursor.fetchone()
        
        if not sale:
            conn.close()
            return jsonify({'error': 'Sale not found'}), 404
        
        # Get sale items
        cursor.execute('SELECT * FROM sale_items WHERE sale_id = ?', (sale_id,))
        items = [dict(item) for item in cursor.fetchall()]
        
        # Get customer details if exists
        customer = None
        if sale['customer_id']:
            cursor.execute(
                'SELECT * FROM customers WHERE id = ?',
                (sale['customer_id'],)
            )
            customer = dict(cursor.fetchone())
        
        conn.close()
        
        sale_dict = dict(sale)
        sale_dict['items'] = items
        sale_dict['customer'] = customer
        
        return jsonify({
            'success': True,
            'sale': sale_dict
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== ANALYTICS ROUTES ====================
@app.route('/api/analytics/dashboard', methods=['GET'])
@login_required
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Today's date
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 1. Sales Statistics
        # Today's sales
        cursor.execute('''
            SELECT 
                COUNT(*) as sales_count,
                SUM(total_amount) as total_sales,
                SUM(total_amount - subtotal + discount) as total_profit,
                SUM(total_items) as items_sold
            FROM sales 
            WHERE DATE(created_at) = DATE('now') 
            AND sale_status = 'completed'
        ''')
        today_stats = cursor.fetchone() or {}
        
        # This month's sales
        cursor.execute('''
            SELECT 
                COUNT(*) as sales_count,
                SUM(total_amount) as total_sales,
                SUM(total_amount - subtotal + discount) as total_profit
            FROM sales 
            WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')
            AND sale_status = 'completed'
        ''')
        month_stats = cursor.fetchone() or {}
        
        # 2. Product Statistics
        cursor.execute('''
            SELECT 
                COUNT(*) as total_products,
                SUM(stock_quantity) as total_stock,
                SUM(cost_price * stock_quantity) as stock_value,
                SUM(selling_price * stock_quantity) as potential_revenue
            FROM products 
            WHERE is_active = 1
        ''')
        product_stats = cursor.fetchone() or {}
        
        # 3. Stock Alerts
        cursor.execute('''
            SELECT COUNT(*) as alert_count
            FROM stock_alerts 
            WHERE is_resolved = 0
        ''')
        alert_count = cursor.fetchone()['alert_count'] or 0
        
        # Low stock items
        cursor.execute('''
            SELECT COUNT(*) as low_stock_count
            FROM products 
            WHERE stock_quantity <= reorder_level 
            AND stock_quantity > 0 
            AND is_active = 1
        ''')
        low_stock_count = cursor.fetchone()['low_stock_count'] or 0
        
        # Out of stock items
        cursor.execute('''
            SELECT COUNT(*) as out_of_stock_count
            FROM products 
            WHERE stock_quantity = 0 AND is_active = 1
        ''')
        out_of_stock_count = cursor.fetchone()['out_of_stock_count'] or 0
        
        # 4. Customer Statistics
        cursor.execute('''
            SELECT 
                COUNT(*) as total_customers,
                SUM(total_orders) as total_orders,
                SUM(total_spent) as total_spent
            FROM customers 
            WHERE is_active = 1
        ''')
        customer_stats = cursor.fetchone() or {}
        
        # 5. Recent Sales (last 10)
        cursor.execute('''
            SELECT s.*, 
                   GROUP_CONCAT(DISTINCT si.product_name) as product_names
            FROM sales s
            LEFT JOIN sale_items si ON s.id = si.sale_id
            WHERE s.sale_status = 'completed'
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT 10
        ''')
        recent_sales = [dict(sale) for sale in cursor.fetchall()]
        
        # 6. Top Selling Products
        cursor.execute('''
            SELECT 
                p.id, p.name, p.sku, p.category_name,
                SUM(si.quantity) as total_sold,
                SUM(si.subtotal) as total_revenue,
                SUM(si.profit) as total_profit
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN sales s ON si.sale_id = s.id
            WHERE s.sale_status = 'completed'
            GROUP BY p.id
            ORDER BY total_sold DESC
            LIMIT 5
        ''')
        top_products = [dict(product) for product in cursor.fetchall()]
        
        # 7. Sales by Category
        cursor.execute('''
            SELECT 
                p.category_name,
                COUNT(DISTINCT s.id) as sale_count,
                SUM(si.quantity) as items_sold,
                SUM(si.subtotal) as revenue,
                SUM(si.profit) as profit
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN sales s ON si.sale_id = s.id
            WHERE s.sale_status = 'completed'
            GROUP BY p.category_name
            ORDER BY revenue DESC
        ''')
        category_sales = [dict(row) for row in cursor.fetchall()]
        
        # 8. Daily Sales for last 7 days
        cursor.execute('''
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as sales_count,
                SUM(total_amount) as total_sales,
                SUM(total_amount - subtotal + discount) as total_profit
            FROM sales
            WHERE created_at >= datetime('now', '-7 days')
            AND sale_status = 'completed'
            GROUP BY DATE(created_at)
            ORDER BY date
        ''')
        daily_sales = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        # Calculate profit margin
        month_profit = month_stats.get('total_profit', 0) or 0
        month_sales = month_stats.get('total_sales', 0) or 0
        profit_margin = (month_profit / month_sales * 100) if month_sales > 0 else 0
        
        return jsonify({
            'success': True,
            'stats': {
                'today': {
                    'sales_count': today_stats.get('sales_count', 0) or 0,
                    'total_sales': today_stats.get('total_sales', 0) or 0,
                    'total_profit': today_stats.get('total_profit', 0) or 0,
                    'items_sold': today_stats.get('items_sold', 0) or 0
                },
                'month': {
                    'sales_count': month_stats.get('sales_count', 0) or 0,
                    'total_sales': month_stats.get('total_sales', 0) or 0,
                    'total_profit': month_stats.get('total_profit', 0) or 0,
                    'profit_margin': round(profit_margin, 2)
                },
                'products': {
                    'total': product_stats.get('total_products', 0) or 0,
                    'total_stock': product_stats.get('total_stock', 0) or 0,
                    'stock_value': product_stats.get('stock_value', 0) or 0,
                    'potential_revenue': product_stats.get('potential_revenue', 0) or 0,
                    'low_stock': low_stock_count,
                    'out_of_stock': out_of_stock_count
                },
                'customers': {
                    'total': customer_stats.get('total_customers', 0) or 0,
                    'total_orders': customer_stats.get('total_orders', 0) or 0,
                    'total_spent': customer_stats.get('total_spent', 0) or 0,
                    'avg_order_value': round(
                        (customer_stats.get('total_spent', 0) or 0) / 
                        (customer_stats.get('total_orders', 1) or 1), 2
                    )
                },
                'alerts': {
                    'total': alert_count
                }
            },
            'recent_sales': recent_sales,
            'top_products': top_products,
            'category_sales': category_sales,
            'daily_sales': daily_sales
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get analytics: {str(e)}'}), 500

@app.route('/api/analytics/financial-report', methods=['GET'])
@login_required
def get_financial_report():
    """Get detailed financial report"""
    try:
        # Get date range
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        if not start_date or not end_date:
            # Default to current month
            today = datetime.now()
            start_date = today.replace(day=1).strftime('%Y-%m-%d')
            end_date = today.strftime('%Y-%m-%d')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Sales Summary
        cursor.execute('''
            SELECT 
                COUNT(*) as sales_count,
                SUM(total_items) as items_sold,
                SUM(subtotal) as subtotal,
                SUM(discount) as discount,
                SUM(tax) as tax,
                SUM(total_amount) as total_sales,
                SUM(total_amount - subtotal + discount) as total_profit
            FROM sales
            WHERE DATE(created_at) BETWEEN ? AND ?
            AND sale_status = 'completed'
        ''', (start_date, end_date))
        
        sales_summary = cursor.fetchone() or {}
        
        # 2. Sales by Payment Method
        cursor.execute('''
            SELECT 
                payment_method,
                COUNT(*) as transaction_count,
                SUM(total_amount) as total_amount
            FROM sales
            WHERE DATE(created_at) BETWEEN ? AND ?
            AND sale_status = 'completed'
            GROUP BY payment_method
            ORDER BY total_amount DESC
        ''', (start_date, end_date))
        
        payment_methods = [dict(row) for row in cursor.fetchall()]
        
        # 3. Top Selling Products
        cursor.execute('''
            SELECT 
                p.id, p.name, p.sku, p.category_name,
                SUM(si.quantity) as quantity_sold,
                SUM(si.subtotal) as revenue,
                SUM(si.profit) as profit,
                ROUND(AVG(si.unit_price), 2) as avg_price
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN sales s ON si.sale_id = s.id
            WHERE DATE(s.created_at) BETWEEN ? AND ?
            AND s.sale_status = 'completed'
            GROUP BY p.id
            ORDER BY revenue DESC
            LIMIT 10
        ''', (start_date, end_date))
        
        top_products = [dict(row) for row in cursor.fetchall()]
        
        # 4. Daily Sales Trend
        cursor.execute('''
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as sales_count,
                SUM(total_amount) as total_sales,
                SUM(total_amount - subtotal + discount) as total_profit
            FROM sales
            WHERE DATE(created_at) BETWEEN ? AND ?
            AND sale_status = 'completed'
            GROUP BY DATE(created_at)
            ORDER BY date
        ''', (start_date, end_date))
        
        daily_trend = [dict(row) for row in cursor.fetchall()]
        
        # 5. Customer Analysis
        cursor.execute('''
            SELECT 
                COUNT(DISTINCT customer_phone) as unique_customers,
                COUNT(DISTINCT CASE WHEN customer_phone = 'N/A' THEN NULL ELSE customer_phone END) as registered_customers,
                ROUND(AVG(total_amount), 2) as avg_sale_value,
                MAX(total_amount) as max_sale_value,
                MIN(total_amount) as min_sale_value
            FROM sales
            WHERE DATE(created_at) BETWEEN ? AND ?
            AND sale_status = 'completed'
        ''', (start_date, end_date))
        
        customer_analysis = cursor.fetchone() or {}
        
        # 6. Category Performance
        cursor.execute('''
            SELECT 
                p.category_name,
                COUNT(DISTINCT s.id) as sales_count,
                SUM(si.quantity) as items_sold,
                SUM(si.subtotal) as revenue,
                SUM(si.profit) as profit,
                ROUND(SUM(si.profit) / SUM(si.subtotal) * 100, 2) as profit_margin
            FROM sale_items si
            JOIN products p ON si.product_id = p.id
            JOIN sales s ON si.sale_id = s.id
            WHERE DATE(s.created_at) BETWEEN ? AND ?
            AND s.sale_status = 'completed'
            GROUP BY p.category_name
            ORDER BY revenue DESC
        ''', (start_date, end_date))
        
        category_performance = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        # Calculate percentages
        total_sales = sales_summary.get('total_sales', 0) or 0
        total_profit = sales_summary.get('total_profit', 0) or 0
        profit_margin = (total_profit / total_sales * 100) if total_sales > 0 else 0
        
        return jsonify({
            'success': True,
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'summary': {
                'sales_count': sales_summary.get('sales_count', 0) or 0,
                'items_sold': sales_summary.get('items_sold', 0) or 0,
                'subtotal': sales_summary.get('subtotal', 0) or 0,
                'discount': sales_summary.get('discount', 0) or 0,
                'tax': sales_summary.get('tax', 0) or 0,
                'total_sales': total_sales,
                'total_profit': total_profit,
                'profit_margin': round(profit_margin, 2),
                'avg_sale_value': round(
                    total_sales / (sales_summary.get('sales_count', 1) or 1), 2
                )
            },
            'payment_methods': payment_methods,
            'top_products': top_products,
            'daily_trend': daily_trend,
            'customer_analysis': customer_analysis,
            'category_performance': category_performance
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate financial report: {str(e)}'}), 500

@app.route('/api/analytics/stock-report', methods=['GET'])
@login_required
def get_stock_report():
    """Get stock analysis report"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Stock Summary
        cursor.execute('''
            SELECT 
                COUNT(*) as total_products,
                SUM(stock_quantity) as total_stock,
                SUM(cost_price * stock_quantity) as total_cost_value,
                SUM(selling_price * stock_quantity) as total_selling_value,
                AVG(cost_price) as avg_cost_price,
                AVG(selling_price) as avg_selling_price,
                AVG(selling_price - cost_price) as avg_profit_per_unit
            FROM products 
            WHERE is_active = 1
        ''')
        
        stock_summary = cursor.fetchone() or {}
        
        # Calculate potential profit
        total_cost = stock_summary.get('total_cost_value', 0) or 0
        total_selling = stock_summary.get('total_selling_value', 0) or 0
        potential_profit = total_selling - total_cost
        
        # 2. Stock by Category
        cursor.execute('''
            SELECT 
                category_name,
                COUNT(*) as product_count,
                SUM(stock_quantity) as total_stock,
                SUM(cost_price * stock_quantity) as cost_value,
                SUM(selling_price * stock_quantity) as selling_value,
                ROUND(AVG(selling_price - cost_price), 2) as avg_profit
            FROM products
            WHERE is_active = 1
            GROUP BY category_name
            ORDER BY cost_value DESC
        ''')
        
        stock_by_category = [dict(row) for row in cursor.fetchall()]
        
        # 3. Low Stock Items
        cursor.execute('''
            SELECT p.*, c.name as category_full_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.stock_quantity <= p.reorder_level 
            AND p.stock_quantity > 0 
            AND p.is_active = 1
            ORDER BY p.stock_quantity ASC
        ''')
        
        low_stock_items = calculate_profit_metrics(cursor.fetchall())
        
        # 4. Out of Stock Items
        cursor.execute('''
            SELECT p.*, c.name as category_full_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.stock_quantity = 0 AND p.is_active = 1
            ORDER BY p.updated_at DESC
        ''')
        
        out_of_stock_items = calculate_profit_metrics(cursor.fetchall())
        
        # 5. Top Valuable Stock
        cursor.execute('''
            SELECT p.*, c.name as category_full_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            WHERE p.is_active = 1
            ORDER BY (p.cost_price * p.stock_quantity) DESC
            LIMIT 10
        ''')
        
        valuable_stock = calculate_profit_metrics(cursor.fetchall())
        
        # 6. Stock Turnover (simplified)
        cursor.execute('''
            SELECT 
                p.id, p.name, p.sku, p.category_name,
                p.initial_stock, p.stock_quantity,
                (p.initial_stock - p.stock_quantity) as sold_quantity,
                CASE 
                    WHEN p.initial_stock > 0 
                    THEN ROUND((p.initial_stock - p.stock_quantity) * 100.0 / p.initial_stock, 2)
                    ELSE 0 
                END as turnover_rate
            FROM products p
            WHERE p.is_active = 1 AND p.initial_stock > 0
            ORDER BY turnover_rate DESC
            LIMIT 10
        ''')
        
        stock_turnover = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'summary': {
                'total_products': stock_summary.get('total_products', 0) or 0,
                'total_stock': stock_summary.get('total_stock', 0) or 0,
                'total_cost_value': round(total_cost, 2),
                'total_selling_value': round(total_selling, 2),
                'potential_profit': round(potential_profit, 2),
                'avg_cost_price': round(stock_summary.get('avg_cost_price', 0) or 0, 2),
                'avg_selling_price': round(stock_summary.get('avg_selling_price', 0) or 0, 2),
                'avg_profit_per_unit': round(stock_summary.get('avg_profit_per_unit', 0) or 0, 2)
            },
            'stock_by_category': stock_by_category,
            'low_stock_items': {
                'count': len(low_stock_items),
                'items': low_stock_items
            },
            'out_of_stock_items': {
                'count': len(out_of_stock_items),
                'items': out_of_stock_items
            },
            'valuable_stock': valuable_stock,
            'stock_turnover': stock_turnover
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to generate stock report: {str(e)}'}), 500

# ==================== CUSTOMERS ROUTES ====================
@app.route('/api/customers', methods=['GET'])
@login_required
def get_customers():
    """Get all customers"""
    try:
        search = request.args.get('search')
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Build query
        query = 'SELECT * FROM customers WHERE 1=1'
        params = []
        
        if search:
            query += ''' AND (
                full_name LIKE ? OR 
                phone LIKE ? OR 
                email LIKE ? OR
                customer_code LIKE ?
            )'''
            search_term = f'%{search}%'
            params.extend([search_term, search_term, search_term, search_term])
        
        query += ''' 
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])
        
        cursor.execute(query, params)
        customers = [dict(cust) for cust in cursor.fetchall()]
        
        # Get total count
        count_query = 'SELECT COUNT(*) as total FROM customers WHERE 1=1'
        count_params = []
        
        if search:
            count_query += ''' AND (
                full_name LIKE ? OR 
                phone LIKE ? OR 
                email LIKE ?
            )'''
            count_params.extend([search_term, search_term, search_term])
        
        cursor.execute(count_query, count_params)
        total = cursor.fetchone()['total']
        
        conn.close()
        
        return jsonify({
            'success': True,
            'customers': customers,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset,
                'has_more': (offset + len(customers)) < total
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/customers/<int:customer_id>', methods=['GET'])
@login_required
def get_customer_details(customer_id):
    """Get customer details with purchase history"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get customer
        cursor.execute('SELECT * FROM customers WHERE id = ?', (customer_id,))
        customer = cursor.fetchone()
        
        if not customer:
            conn.close()
            return jsonify({'error': 'Customer not found'}), 404
        
        # Get purchase history
        cursor.execute('''
            SELECT s.*, 
                   GROUP_CONCAT(DISTINCT si.product_name) as product_names
            FROM sales s
            LEFT JOIN sale_items si ON s.id = si.sale_id
            WHERE s.customer_phone = ? AND s.sale_status = 'completed'
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT 20
        ''', (customer['phone'],))
        
        purchase_history = [dict(sale) for sale in cursor.fetchall()]
        
        # Get total purchase summary
        cursor.execute('''
            SELECT 
                COUNT(*) as total_orders,
                SUM(total_amount) as total_spent,
                AVG(total_amount) as avg_order_value,
                MIN(created_at) as first_order,
                MAX(created_at) as last_order
            FROM sales
            WHERE customer_phone = ? AND sale_status = 'completed'
        ''', (customer['phone'],))
        
        purchase_summary = cursor.fetchone() or {}
        
        conn.close()
        
        customer_dict = dict(customer)
        customer_dict['purchase_history'] = purchase_history
        customer_dict['purchase_summary'] = dict(purchase_summary)
        
        return jsonify({
            'success': True,
            'customer': customer_dict
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== STOCK ALERTS ROUTES ====================
@app.route('/api/alerts', methods=['GET'])
@login_required
def get_stock_alerts():
    """Get all stock alerts"""
    try:
        resolved = request.args.get('resolved', 'false').lower() == 'true'
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        query = '''
            SELECT sa.*, p.sku, p.image_url
            FROM stock_alerts sa
            LEFT JOIN products p ON sa.product_id = p.id
        '''
        
        if not resolved:
            query += ' WHERE sa.is_resolved = 0'
        
        query += ' ORDER BY sa.created_at DESC'
        
        cursor.execute(query)
        alerts = [dict(alert) for alert in cursor.fetchall()]
        
        conn.close()
        
        return jsonify({
            'success': True,
            'alerts': alerts,
            'count': len(alerts)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/alerts/<int:alert_id>/resolve', methods=['PUT'])
@login_required
def resolve_alert(alert_id):
    """Resolve stock alert"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if alert exists
        cursor.execute('SELECT * FROM stock_alerts WHERE id = ?', (alert_id,))
        alert = cursor.fetchone()
        
        if not alert:
            conn.close()
            return jsonify({'error': 'Alert not found'}), 404
        
        # Resolve alert
        cursor.execute('''
            UPDATE stock_alerts 
            SET is_resolved = 1, 
                resolved_at = CURRENT_TIMESTAMP,
                resolved_by = ?
            WHERE id = ?
        ''', (request.current_user['id'], alert_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Alert resolved successfully'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== HEALTH CHECK ====================
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check database
        cursor.execute('SELECT 1')
        db_ok = cursor.fetchone() is not None
        
        # Check tables
        tables = ['admin_users', 'products', 'sales', 'customers']
        tables_ok = {}
        
        for table in tables:
            try:
                cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
                tables_ok[table] = cursor.fetchone()['count'] >= 0
            except:
                tables_ok[table] = False
        
        conn.close()
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected' if db_ok else 'disconnected',
            'tables': tables_ok,
            'version': '1.0.0'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Endpoint not found', 'code': 'NOT_FOUND'}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({'error': 'Method not allowed', 'code': 'METHOD_NOT_ALLOWED'}), 405

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f'Server Error: {error}')
    return jsonify({'error': 'Internal server error', 'code': 'INTERNAL_ERROR'}), 500

@app.errorhandler(413)
def too_large(error):
    return jsonify({'error': 'File too large', 'code': 'FILE_TOO_LARGE'}), 413

# ==================== APPLICATION STARTUP ====================
if __name__ == '__main__':
    # Initialize database
    print("🚀 Initializing Karanja Shoe Store Admin Backend...")
    init_database()
    
    # Start server
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"✅ Database initialized successfully!")
    print(f"🌐 Server starting on http://0.0.0.0:{port}")
    print(f"📧 Default Admin: admin / admin123")
    print(f"🔧 Debug mode: {debug}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
