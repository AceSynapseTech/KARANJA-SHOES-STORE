"""
KARANJA SHOE STORE - ULTRA SIMPLE ADMIN BACKEND
Works on Render with Python 3.13 - No dependency issues
"""

import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, Response

# Initialize Flask app
app = Flask(__name__)

# Enable CORS for all routes
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# Database setup
def init_db():
    """Initialize the database"""
    conn = sqlite3.connect('karanja.db')
    c = conn.cursor()
    
    # Create tables
    c.execute('''
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            full_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            size TEXT NOT NULL,
            color TEXT,
            cost_price REAL NOT NULL,
            selling_price REAL NOT NULL,
            stock_quantity INTEGER DEFAULT 0,
            reorder_level INTEGER DEFAULT 5,
            image_url TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_no TEXT UNIQUE NOT NULL,
            product_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            total_amount REAL NOT NULL,
            cost_price REAL NOT NULL,
            profit REAL NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            payment_method TEXT DEFAULT 'cash',
            sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products (id)
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            email TEXT,
            total_purchases INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,
            last_purchase TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default admin if not exists
    c.execute("SELECT id FROM admin WHERE username = 'admin'")
    if not c.fetchone():
        c.execute(
            "INSERT INTO admin (username, password, email, full_name) VALUES (?, ?, ?, ?)",
            ('admin', 'admin123', 'admin@karanjashoestore.co.ke', 'Admin Karanja')
        )
    
    conn.commit()
    conn.close()
    print("✅ Database initialized!")

# Database connection helper
def get_db():
    conn = sqlite3.connect('karanja.db')
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

# Simple authentication (for demo only - use JWT in production)
def authenticate(token):
    """Simple token authentication"""
    return token == "admin_token"  # In production, use proper JWT

# Routes
@app.route('/')
def home():
    return jsonify({
        'message': 'Karanja Shoe Store Admin API',
        'version': '1.0',
        'status': 'running',
        'endpoints': {
            'auth': ['POST /api/login'],
            'products': ['GET /api/products', 'POST /api/products', 'PUT /api/products/<id>', 'DELETE /api/products/<id>'],
            'sales': ['GET /api/sales', 'POST /api/sales'],
            'analytics': ['GET /api/dashboard'],
            'customers': ['GET /api/customers']
        }
    })

# Authentication
@app.route('/api/login', methods=['POST'])
def login():
    """Admin login"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        conn = get_db()
        user = conn.execute(
            'SELECT * FROM admin WHERE username = ? AND password = ?',
            (username, password)
        ).fetchone()
        conn.close()
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'token': 'admin_token',  # Simple token for demo
            'user': {
                'id': user['id'],
                'username': user['username'],
                'email': user['email'],
                'full_name': user['full_name']
            }
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Products CRUD
@app.route('/api/products', methods=['GET'])
def get_products():
    """Get all products"""
    try:
        conn = get_db()
        
        # Get filters
        category = request.args.get('category')
        search = request.args.get('search', '').strip()
        
        query = "SELECT * FROM products WHERE 1=1"
        params = []
        
        if category:
            query += " AND category = ?"
            params.append(category)
        
        if search:
            query += " AND (name LIKE ? OR sku LIKE ? OR description LIKE ?)"
            search_term = f'%{search}%'
            params.extend([search_term, search_term, search_term])
        
        query += " ORDER BY created_at DESC"
        
        products = conn.execute(query, params).fetchall()
        conn.close()
        
        # Convert to list of dicts
        products_list = []
        for p in products:
            product = dict(p)
            # Calculate profit metrics
            cost = product.get('cost_price', 0) or 0
            sell = product.get('selling_price', 0) or 0
            stock = product.get('stock_quantity', 0) or 0
            
            product['profit_per_unit'] = round(sell - cost, 2)
            product['profit_margin'] = round(((sell - cost) / cost * 100) if cost > 0 else 0, 2)
            product['stock_value'] = round(cost * stock, 2)
            product['potential_revenue'] = round(sell * stock, 2)
            product['total_profit_potential'] = round((sell - cost) * stock, 2)
            
            # Add status
            if stock <= 0:
                product['status'] = 'Out of Stock'
                product['status_color'] = 'danger'
            elif stock <= product.get('reorder_level', 5):
                product['status'] = 'Low Stock'
                product['status_color'] = 'warning'
            else:
                product['status'] = 'In Stock'
                product['status_color'] = 'success'
            
            products_list.append(product)
        
        return jsonify({
            'success': True,
            'products': products_list,
            'count': len(products_list)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    """Get single product"""
    try:
        conn = get_db()
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?',
            (product_id,)
        ).fetchone()
        conn.close()
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        product_dict = dict(product)
        
        # Calculate profit metrics
        cost = product_dict.get('cost_price', 0) or 0
        sell = product_dict.get('selling_price', 0) or 0
        stock = product_dict.get('stock_quantity', 0) or 0
        
        product_dict['profit_per_unit'] = round(sell - cost, 2)
        product_dict['profit_margin'] = round(((sell - cost) / cost * 100) if cost > 0 else 0, 2)
        product_dict['stock_value'] = round(cost * stock, 2)
        product_dict['potential_revenue'] = round(sell * stock, 2)
        product_dict['total_profit_potential'] = round((sell - cost) * stock, 2)
        
        return jsonify({
            'success': True,
            'product': product_dict
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products', methods=['POST'])
def create_product():
    """Create new product"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required = ['name', 'category', 'size', 'cost_price', 'selling_price']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field.replace("_", " ").title()} is required'}), 400
        
        # Generate SKU
        import random
        category_code = data['category'][:3].upper()
        sku = f"{category_code}-{data['size']}-{random.randint(1000, 9999)}"
        
        conn = get_db()
        
        # Check if SKU exists
        existing = conn.execute(
            'SELECT id FROM products WHERE sku = ?',
            (sku,)
        ).fetchone()
        
        if existing:
            conn.close()
            return jsonify({'error': 'SKU already exists. Try again.'}), 400
        
        # Insert product
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO products 
            (sku, name, category, size, color, cost_price, selling_price, 
             stock_quantity, reorder_level, image_url, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sku,
            data['name'],
            data['category'],
            data['size'],
            data.get('color', ''),
            float(data['cost_price']),
            float(data['selling_price']),
            int(data.get('stock_quantity', 0)),
            int(data.get('reorder_level', 5)),
            data.get('image_url', ''),
            data.get('description', '')
        ))
        
        product_id = cursor.lastrowid
        conn.commit()
        
        # Get the created product
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?',
            (product_id,)
        ).fetchone()
        
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Product created successfully',
            'product': dict(product)
        }), 201
    
    except Exception as e:
        return jsonify({'error': f'Failed to create product: {str(e)}'}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Update product"""
    try:
        data = request.get_json()
        
        conn = get_db()
        
        # Check if product exists
        existing = conn.execute(
            'SELECT id FROM products WHERE id = ?',
            (product_id,)
        ).fetchone()
        
        if not existing:
            conn.close()
            return jsonify({'error': 'Product not found'}), 404
        
        # Build update query
        fields = []
        values = []
        
        update_fields = [
            'name', 'category', 'size', 'color', 'cost_price',
            'selling_price', 'stock_quantity', 'reorder_level',
            'image_url', 'description'
        ]
        
        for field in update_fields:
            if field in data:
                fields.append(f"{field} = ?")
                values.append(data[field])
        
        if not fields:
            conn.close()
            return jsonify({'error': 'No fields to update'}), 400
        
        # Add updated timestamp
        fields.append('updated_at = CURRENT_TIMESTAMP')
        
        # Execute update
        values.append(product_id)
        query = f"UPDATE products SET {', '.join(fields)} WHERE id = ?"
        
        conn.execute(query, values)
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Product updated successfully'
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to update product: {str(e)}'}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete product"""
    try:
        conn = get_db()
        
        # Check if product exists
        product = conn.execute(
            'SELECT * FROM products WHERE id = ?',
            (product_id,)
        ).fetchone()
        
        if not product:
            conn.close()
            return jsonify({'error': 'Product not found'}), 404
        
        # Check if product has sales
        sales_count = conn.execute(
            'SELECT COUNT(*) as count FROM sales WHERE product_id = ?',
            (product_id,)
        ).fetchone()['count']
        
        if sales_count > 0:
            # Soft delete by setting stock to 0 and marking
            conn.execute('''
                UPDATE products 
                SET stock_quantity = 0, 
                    description = COALESCE(description, '') || ' [DELETED]'
                WHERE id = ?
            ''', (product_id,))
            message = 'Product deactivated (has sales history)'
        else:
            # Hard delete
            conn.execute('DELETE FROM products WHERE id = ?', (product_id,))
            message = 'Product deleted successfully'
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': message
        })
    
    except Exception as e:
        return jsonify({'error': f'Failed to delete product: {str(e)}'}), 500

# Sales
@app.route('/api/sales', methods=['GET'])
def get_sales():
    """Get all sales"""
    try:
        conn = get_db()
        
        # Get filters
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = '''
            SELECT s.*, p.name as product_name, p.sku
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            WHERE 1=1
        '''
        params = []
        
        if start_date:
            query += " AND DATE(s.sale_date) >= DATE(?)"
            params.append(start_date)
        
        if end_date:
            query += " AND DATE(s.sale_date) <= DATE(?)"
            params.append(end_date)
        
        query += " ORDER BY s.sale_date DESC"
        
        sales = conn.execute(query, params).fetchall()
        conn.close()
        
        sales_list = [dict(sale) for sale in sales]
        
        return jsonify({
            'success': True,
            'sales': sales_list,
            'count': len(sales_list)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales', methods=['POST'])
def create_sale():
    """Create new sale"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required = ['product_id', 'quantity', 'customer_name', 'customer_phone']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field.replace("_", " ").title()} is required'}), 400
        
        conn = get_db()
        
        # Get product details
        product = conn.execute('''
            SELECT id, name, cost_price, selling_price, stock_quantity 
            FROM products 
            WHERE id = ?
        ''', (data['product_id'],)).fetchone()
        
        if not product:
            conn.close()
            return jsonify({'error': 'Product not found'}), 404
        
        # Check stock
        if product['stock_quantity'] < data['quantity']:
            conn.close()
            return jsonify({
                'error': f"Insufficient stock. Available: {product['stock_quantity']}"
            }), 400
        
        # Calculate amounts
        quantity = int(data['quantity'])
        unit_price = float(data.get('unit_price', product['selling_price']))
        cost_price = product['cost_price']
        total_amount = unit_price * quantity
        profit = (unit_price - cost_price) * quantity
        
        # Generate invoice number
        import random
        invoice_no = f"INV-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        
        # Create sale
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO sales 
            (invoice_no, product_id, product_name, quantity, unit_price, 
             total_amount, cost_price, profit, customer_name, customer_phone, payment_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            invoice_no,
            product['id'],
            product['name'],
            quantity,
            unit_price,
            total_amount,
            cost_price,
            profit,
            data['customer_name'],
            data['customer_phone'],
            data.get('payment_method', 'cash')
        ))
        
        # Update product stock
        conn.execute('''
            UPDATE products 
            SET stock_quantity = stock_quantity - ?
            WHERE id = ?
        ''', (quantity, product['id']))
        
        # Update or create customer
        customer = conn.execute(
            'SELECT id FROM customers WHERE phone = ?',
            (data['customer_phone'],)
        ).fetchone()
        
        if customer:
            # Update existing customer
            conn.execute('''
                UPDATE customers 
                SET total_purchases = total_purchases + 1,
                    total_spent = total_spent + ?,
                    last_purchase = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (total_amount, customer['id']))
        else:
            # Create new customer
            conn.execute('''
                INSERT INTO customers 
                (name, phone, email, total_purchases, total_spent, last_purchase)
                VALUES (?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
            ''', (
                data['customer_name'],
                data['customer_phone'],
                data.get('customer_email', ''),
                total_amount
            ))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': 'Sale recorded successfully',
            'invoice_no': invoice_no,
            'total_amount': total_amount,
            'profit': profit
        }), 201
    
    except Exception as e:
        return jsonify({'error': f'Failed to record sale: {str(e)}'}), 500

# Analytics Dashboard
@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    """Get dashboard statistics"""
    try:
        conn = get_db()
        
        # 1. Total Products
        total_products = conn.execute(
            'SELECT COUNT(*) as count FROM products'
        ).fetchone()['count']
        
        # 2. Total Stock Value
        stock_value = conn.execute('''
            SELECT SUM(cost_price * stock_quantity) as value 
            FROM products
        ''').fetchone()['value'] or 0
        
        # 3. Low Stock Items
        low_stock = conn.execute('''
            SELECT COUNT(*) as count 
            FROM products 
            WHERE stock_quantity <= reorder_level AND stock_quantity > 0
        ''').fetchone()['count']
        
        # 4. Out of Stock Items
        out_of_stock = conn.execute('''
            SELECT COUNT(*) as count 
            FROM products 
            WHERE stock_quantity = 0
        ''').fetchone()['count']
        
        # 5. Today's Sales
        today_sales = conn.execute('''
            SELECT 
                COUNT(*) as count,
                SUM(total_amount) as amount,
                SUM(profit) as profit
            FROM sales 
            WHERE DATE(sale_date) = DATE('now')
        ''').fetchone()
        
        # 6. This Month's Sales
        month_sales = conn.execute('''
            SELECT 
                COUNT(*) as count,
                SUM(total_amount) as amount,
                SUM(profit) as profit
            FROM sales 
            WHERE strftime('%Y-%m', sale_date) = strftime('%Y-%m', 'now')
        ''').fetchone()
        
        # 7. Total Customers
        total_customers = conn.execute(
            'SELECT COUNT(*) as count FROM customers'
        ).fetchone()['count']
        
        # 8. Recent Sales (last 10)
        recent_sales = conn.execute('''
            SELECT s.*, p.name as product_name
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.id
            ORDER BY s.sale_date DESC
            LIMIT 10
        ''').fetchall()
        
        # 9. Top Selling Products
        top_products = conn.execute('''
            SELECT 
                p.id, p.name, p.sku, p.category,
                SUM(s.quantity) as total_sold,
                SUM(s.total_amount) as total_revenue,
                SUM(s.profit) as total_profit
            FROM sales s
            JOIN products p ON s.product_id = p.id
            GROUP BY p.id
            ORDER BY total_sold DESC
            LIMIT 5
        ''').fetchall()
        
        # 10. Sales by Category
        category_sales = conn.execute('''
            SELECT 
                p.category,
                COUNT(DISTINCT s.id) as sales_count,
                SUM(s.quantity) as items_sold,
                SUM(s.total_amount) as revenue,
                SUM(s.profit) as profit
            FROM sales s
            JOIN products p ON s.product_id = p.id
            GROUP BY p.category
            ORDER BY revenue DESC
        ''').fetchall()
        
        conn.close()
        
        # Format data
        stats = {
            'products': {
                'total': total_products,
                'stock_value': round(stock_value, 2),
                'low_stock': low_stock,
                'out_of_stock': out_of_stock
            },
            'sales': {
                'today': {
                    'count': today_sales['count'] or 0,
                    'amount': today_sales['amount'] or 0,
                    'profit': today_sales['profit'] or 0
                },
                'month': {
                    'count': month_sales['count'] or 0,
                    'amount': month_sales['amount'] or 0,
                    'profit': month_sales['profit'] or 0,
                    'profit_margin': round(
                        ((month_sales['profit'] or 0) / (month_sales['amount'] or 1) * 100), 
                        2
                    ) if month_sales['amount'] else 0
                }
            },
            'customers': {
                'total': total_customers
            }
        }
        
        return jsonify({
            'success': True,
            'stats': stats,
            'recent_sales': [dict(sale) for sale in recent_sales],
            'top_products': [dict(product) for product in top_products],
            'category_sales': [dict(cat) for cat in category_sales]
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Customers
@app.route('/api/customers', methods=['GET'])
def get_customers():
    """Get all customers"""
    try:
        conn = get_db()
        
        search = request.args.get('search', '').strip()
        
        query = "SELECT * FROM customers WHERE 1=1"
        params = []
        
        if search:
            query += " AND (name LIKE ? OR phone LIKE ? OR email LIKE ?)"
            search_term = f'%{search}%'
            params.extend([search_term, search_term, search_term])
        
        query += " ORDER BY created_at DESC"
        
        customers = conn.execute(query, params).fetchall()
        conn.close()
        
        customers_list = [dict(cust) for cust in customers]
        
        return jsonify({
            'success': True,
            'customers': customers_list,
            'count': len(customers_list)
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Health check
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'service': 'Karanja Shoe Store Admin API'
    })

# Initialize database on startup
init_db()

# Run the application
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"🚀 Karanja Shoe Store Admin Backend starting on port {port}")
    print(f"📧 Default Admin: admin / admin123")
    app.run(host='0.0.0.0', port=port, debug=False)
