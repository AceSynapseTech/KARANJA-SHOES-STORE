"""
KARANJA SHOE STORE - SIMPLIFIED VERSION
Works on Render with no complex dependencies
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import pytz

load_dotenv()

# ==================== CONFIGURATION ====================
class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key')
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # Business Settings
    CURRENCY = 'KES'
    LOW_STOCK_THRESHOLD = 3
    OLD_STOCK_DAYS = 30
    TITHE_PERCENTAGE = 10
    SAVINGS_PERCENTAGE = 20
    RESTOCK_PERCENTAGE = 30
    DEDUCTIONS_PERCENTAGE = 15
    PERSONAL_INCOME_PERCENTAGE = 25
    BUSINESS_HEALTH_GOAL = 10000
    
    # Admin credentials
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@karanjashoes.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    
    # Data directory - MUST be writable on Render
    DATA_DIR = '/tmp/karanja-data'


# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    def __init__(self):
        self.data_dir = Config.DATA_DIR
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.products_file = os.path.join(self.data_dir, 'products.json')
        self.sales_file = os.path.join(self.data_dir, 'sales.json')
        self.notifications_file = os.path.join(self.data_dir, 'notifications.json')
        
        self.products = self.load_json(self.products_file, [])
        self.sales = self.load_json(self.sales_file, [])
        self.notifications = self.load_json(self.notifications_file, [])
        
        print(f"✅ Database initialized at: {self.data_dir}")
        print(f"📊 Products: {len(self.products)} | Sales: {len(self.sales)}")
    
    def load_json(self, filepath, default):
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading {filepath}: {e}")
        return default
    
    def save_json(self, filepath, data):
        try:
            with open(filepath, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving {filepath}: {e}")
            return False
    
    # Products
    def get_products(self):
        return self.products
    
    def get_product(self, product_id):
        for p in self.products:
            if p.get('id') == product_id:
                return p
        return None
    
    def add_product(self, data):
        product = {
            'id': str(uuid.uuid4()),
            'name': data.get('name', ''),
            'sku': data.get('sku', ''),
            'category': data.get('category', ''),
            'color': data.get('color', ''),
            'sizes': data.get('sizes', {}),
            'buy_price': float(data.get('buy_price', 0)),
            'min_sell_price': float(data.get('min_sell_price', 0)),
            'max_sell_price': float(data.get('max_sell_price', 0)),
            'description': data.get('description', ''),
            'image': data.get('image', 'https://via.placeholder.com/300'),
            'date_added': datetime.now().isoformat(),
            'total_stock': self.calculate_stock(data.get('sizes', {}))
        }
        self.products.append(product)
        self.save_json(self.products_file, self.products)
        return product
    
    def update_product(self, product_id, updates):
        for i, p in enumerate(self.products):
            if p.get('id') == product_id:
                p.update(updates)
                if 'sizes' in updates:
                    p['total_stock'] = self.calculate_stock(p['sizes'])
                self.products[i] = p
                self.save_json(self.products_file, self.products)
                return p
        return None
    
    def delete_product(self, product_id):
        for i, p in enumerate(self.products):
            if p.get('id') == product_id:
                deleted = self.products.pop(i)
                self.save_json(self.products_file, self.products)
                return deleted
        return None
    
    def calculate_stock(self, sizes):
        total = 0
        for size, stock in sizes.items():
            try:
                total += int(stock)
            except:
                pass
        return total
    
    # Sales
    def get_sales(self):
        return self.sales
    
    def add_sale(self, data):
        sale = {
            'id': str(uuid.uuid4()),
            'product_id': data.get('product_id'),
            'product_name': data.get('product_name'),
            'product_sku': data.get('product_sku'),
            'size': data.get('size'),
            'quantity': int(data.get('quantity', 1)),
            'unit_price': float(data.get('unit_price', 0)),
            'unit_cost': float(data.get('unit_cost', 0)),
            'total_amount': int(data.get('quantity', 1)) * float(data.get('unit_price', 0)),
            'total_profit': (int(data.get('quantity', 1)) * float(data.get('unit_price', 0))) - 
                           (int(data.get('quantity', 1)) * float(data.get('unit_cost', 0))),
            'customer_name': data.get('customer_name', 'Walk-in Customer'),
            'notes': data.get('notes', ''),
            'is_bargain': data.get('is_bargain', False),
            'timestamp': datetime.now().isoformat()
        }
        
        self.sales.insert(0, sale)
        if len(self.sales) > 1000:
            self.sales = self.sales[:1000]
        self.save_json(self.sales_file, self.sales)
        
        # Update stock
        product = self.get_product(sale['product_id'])
        if product and 'sizes' in product:
            size = str(sale['size'])
            if size in product['sizes']:
                product['sizes'][size] = max(0, int(product['sizes'][size]) - sale['quantity'])
                self.update_product(product['id'], {'sizes': product['sizes']})
        
        return sale
    
    def get_today_sales(self):
        today = datetime.now().date()
        result = []
        for sale in self.sales:
            try:
                sale_date = datetime.fromisoformat(sale['timestamp']).date()
                if sale_date == today:
                    result.append(sale)
            except:
                pass
        return result
    
    def get_sales_by_period(self, days):
        cutoff = datetime.now() - timedelta(days=days)
        result = []
        for sale in self.sales:
            try:
                sale_date = datetime.fromisoformat(sale['timestamp'])
                if sale_date >= cutoff:
                    result.append(sale)
            except:
                pass
        return result
    
    # Notifications
    def add_notification(self, message, type='info'):
        notification = {
            'id': str(uuid.uuid4()),
            'message': message,
            'type': type,
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        self.notifications.insert(0, notification)
        if len(self.notifications) > 100:
            self.notifications = self.notifications[:100]
        self.save_json(self.notifications_file, self.notifications)
        return notification
    
    def get_notifications(self, limit=20):
        return sorted(self.notifications, key=lambda x: x.get('timestamp', ''), reverse=True)[:limit]
    
    def mark_notifications_read(self):
        for n in self.notifications:
            n['read'] = True
        self.save_json(self.notifications_file, self.notifications)
    
    def get_unread_count(self):
        return sum(1 for n in self.notifications if not n.get('read', False))
    
    # Stats
    def get_dashboard_stats(self, days=None):
        if days:
            sales = self.get_sales_by_period(days)
        else:
            sales = self.sales
        
        today_sales = self.get_today_sales()
        
        return {
            'total_sales': sum(s.get('total_amount', 0) for s in sales),
            'total_profit': sum(s.get('total_profit', 0) for s in sales),
            'total_stock': sum(p.get('total_stock', 0) for p in self.products),
            'total_products': len(self.products),
            'today_sales': sum(s.get('total_amount', 0) for s in today_sales),
            'today_profit': sum(s.get('total_profit', 0) for s in today_sales),
            'today_items': sum(s.get('quantity', 0) for s in today_sales)
        }
    
    # Business Plan
    def get_business_plan(self):
        total_profit = sum(s.get('total_profit', 0) for s in self.sales)
        total_revenue = sum(s.get('total_amount', 0) for s in self.sales)
        
        return {
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'tithe': total_profit * 0.1,
            'savings': total_profit * 0.2,
            'restock': total_profit * 0.3,
            'deductions': total_profit * 0.15,
            'personal_income': total_profit * 0.25,
            'profit_margin': (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        }
    
    def get_business_health(self):
        revenue = sum(s.get('total_amount', 0) for s in self.sales)
        profit = sum(s.get('total_profit', 0) for s in self.sales)
        
        revenue_score = min(100, (revenue / 10000) * 100)
        profit_margin = (profit / revenue * 100) if revenue > 0 else 0
        profit_score = min(100, profit_margin * 2)
        health_score = int((revenue_score * 0.5) + (profit_score * 0.5))
        
        if health_score >= 80:
            status = "Excellent"
        elif health_score >= 60:
            status = "Good"
        elif health_score >= 40:
            status = "Fair"
        else:
            status = "Needs Improvement"
        
        return {'score': health_score, 'status': status}
    
    # Stock Alerts
    def get_stock_alerts(self):
        alerts = []
        for product in self.products:
            for size, stock in product.get('sizes', {}).items():
                try:
                    if 0 < int(stock) <= Config.LOW_STOCK_THRESHOLD:
                        alerts.append({
                            'type': 'low_stock',
                            'product': product.get('name'),
                            'size': size,
                            'stock': int(stock),
                            'message': f"{product.get('name')} (Size {size}) - only {stock} left!"
                        })
                except:
                    pass
        return alerts
    
    @staticmethod
    def format_currency(amount):
        return f"KES {float(amount):,.2f}"


# ==================== FLASK APP ====================
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
CORS(app)

db = DatabaseManager()


# ==================== AUTH DECORATOR ====================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


# ==================== ROUTES ====================
@app.route('/')
def index():
    """Serve the main application"""
    template_path = os.path.join(app.root_path, 'templates', 'index.html')
    
    # Check if template exists
    if not os.path.exists(template_path):
        print(f"❌ TEMPLATE NOT FOUND: {template_path}")
        return f"""
        <html>
            <head><title>Karanja Shoe Store - Error</title></head>
            <body style="font-family: Arial; padding: 40px; text-align: center;">
                <h1 style="color: #ff5722;">⚠️ Template Not Found</h1>
                <p>The application is running but the HTML template is missing.</p>
                <p><strong>Expected path:</strong> {template_path}</p>
                <p><strong>Current directory:</strong> {os.getcwd()}</p>
                <p><strong>Files in current directory:</strong></p>
                <pre>{os.listdir('.')}</pre>
                <p><strong>Files in templates directory (if exists):</strong></p>
                <pre>{os.listdir('templates') if os.path.exists('templates') else 'templates/ directory not found'}</pre>
                <hr>
                <p><strong>Solution:</strong> Create the templates folder and add index.html</p>
                <pre style="background: #f4f4f4; padding: 20px; text-align: left;">
mkdir -p templates
# Copy your HTML code to templates/index.html
                </pre>
            </body>
        </html>
        """, 200
    
    try:
        return render_template('index.html')
    except Exception as e:
        return f"Error rendering template: {str(e)}", 500


@app.route('/api/health')
def health():
    template_path = os.path.join(app.root_path, 'templates', 'index.html')
    return jsonify({
        'status': 'ok',
        'template_exists': os.path.exists(template_path),
        'template_path': template_path,
        'data_dir': db.data_dir,
        'data_writable': os.access(db.data_dir, os.W_OK) if os.path.exists(db.data_dir) else False,
        'products': len(db.products),
        'sales': len(db.sales)
    })


# ==================== AUTH ====================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if data.get('email') == Config.ADMIN_EMAIL and data.get('password') == Config.ADMIN_PASSWORD:
        session['logged_in'] = True
        session['user'] = {'email': Config.ADMIN_EMAIL, 'name': 'Admin Karanja'}
        return jsonify({'success': True, 'user': session['user']})
    return jsonify({'success': False, 'error': 'Invalid credentials'}), 401


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/api/session')
def get_session():
    return jsonify({
        'logged_in': session.get('logged_in', False),
        'user': session.get('user')
    })


# ==================== PRODUCTS ====================
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    return jsonify(db.get_products())


@app.route('/api/products', methods=['POST'])
@login_required
def create_product():
    try:
        data = request.form.to_dict()
        
        # Parse sizes JSON
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        product = db.add_product(data)
        db.add_notification(f"New product: {product.get('name')}", 'success')
        return jsonify(product), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    try:
        data = request.form.to_dict()
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        product = db.update_product(product_id, data)
        if product:
            return jsonify(product)
        return jsonify({'error': 'Not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    product = db.delete_product(product_id)
    if product:
        db.add_notification(f"Deleted: {product.get('name')}", 'warning')
        return jsonify({'success': True})
    return jsonify({'error': 'Not found'}), 404


# ==================== SALES ====================
@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    period = request.args.get('period')
    if period == 'today':
        sales = db.get_today_sales()
    elif period == '7days':
        sales = db.get_sales_by_period(7)
    elif period == '30days':
        sales = db.get_sales_by_period(30)
    else:
        sales = db.get_sales()
    return jsonify(sales)


@app.route('/api/sales', methods=['POST'])
@login_required
def create_sale():
    try:
        data = request.json
        sale = db.add_sale(data)
        
        # Add alerts
        for alert in db.get_stock_alerts()[:3]:
            db.add_notification(alert['message'], 'warning')
        
        return jsonify(sale), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== STATS ====================
@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    period = request.args.get('period', 'today')
    days = {'today': 1, '7days': 7, '1month': 30, '6months': 180}.get(period)
    stats = db.get_dashboard_stats(days)
    stats['period'] = period
    return jsonify(stats)


# ==================== NOTIFICATIONS ====================
@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    return jsonify({
        'notifications': db.get_notifications(),
        'unread_count': db.get_unread_count()
    })


@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_read():
    db.mark_notifications_read()
    return jsonify({'success': True})


# ==================== ALERTS ====================
@app.route('/api/alerts/stock', methods=['GET'])
@login_required
def get_alerts():
    return jsonify(db.get_stock_alerts())


# ==================== BUSINESS ====================
@app.route('/api/business/plan', methods=['GET'])
@login_required
def get_plan():
    return jsonify(db.get_business_plan())


@app.route('/api/business/health', methods=['GET'])
@login_required
def get_health():
    return jsonify(db.get_business_health())


# ==================== CHARTS ====================
@app.route('/api/charts/sales', methods=['GET'])
@login_required
def sales_chart():
    days = int(request.args.get('days', 7))
    sales = db.get_sales_by_period(days)
    
    labels = []
    data = []
    today = datetime.now()
    
    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        labels.append(date.strftime('%b %d'))
        
        daily = 0
        for sale in sales:
            try:
                if datetime.fromisoformat(sale['timestamp']).date() == date.date():
                    daily += sale.get('total_amount', 0)
            except:
                pass
        data.append(daily)
    
    return jsonify({
        'labels': labels,
        'datasets': [{
            'label': 'Sales (KES)',
            'data': data,
            'borderColor': '#2196f3'
        }]
    })


@app.route('/api/charts/top-products', methods=['GET'])
@login_required
def top_products():
    days = int(request.args.get('days', 7))
    sales = db.get_sales_by_period(days)
    
    product_sales = {}
    for sale in sales:
        name = sale.get('product_name', 'Unknown')
        product_sales[name] = product_sales.get(name, 0) + sale.get('quantity', 0)
    
    sorted_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    
    return jsonify({
        'labels': [p[0] for p in sorted_products],
        'datasets': [{
            'label': 'Units Sold',
            'data': [p[1] for p in sorted_products],
            'backgroundColor': '#ff5722'
        }]
    })


# ==================== INIT SAMPLE DATA ====================
@app.route('/api/init/sample-data', methods=['POST'])
@login_required
def init_sample():
    if len(db.get_products()) > 0:
        return jsonify({'message': 'Products exist'}), 400
    
    sample = [
        {
            'name': 'Nike Air Max',
            'sku': 'KS-001',
            'category': 'Sports Shoes',
            'color': 'Black/White',
            'sizes': {'42': 10, '43': 8, '44': 5},
            'buy_price': 3500,
            'min_sell_price': 4500,
            'max_sell_price': 5500,
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=300'
        },
        {
            'name': 'Adidas Stan Smith',
            'sku': 'KS-002',
            'category': 'Casual Shoes',
            'color': 'White',
            'sizes': {'41': 7, '42': 12, '43': 9},
            'buy_price': 2800,
            'min_sell_price': 3800,
            'max_sell_price': 4800,
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=300'
        }
    ]
    
    for p in sample:
        db.add_product(p)
    
    for p in db.get_products()[:2]:
        sizes = list(p.get('sizes', {}).keys())
        if sizes:
            db.add_sale({
                'product_id': p['id'],
                'product_name': p['name'],
                'product_sku': p['sku'],
                'size': sizes[0],
                'quantity': 2,
                'unit_price': p['max_sell_price'],
                'unit_cost': p['buy_price']
            })
    
    db.add_notification('Sample data created!', 'success')
    return jsonify({'success': True})


# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Server error'}), 500


# ==================== MAIN ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    print("\n" + "="*50)
    print("🚀 KARANJA SHOE STORE")
    print("="*50)
    print(f"📁 Data directory: {Config.DATA_DIR}")
    print(f"📁 Template path: {os.path.join(app.root_path, 'templates', 'index.html')}")
    print(f"📁 Template exists: {os.path.exists(os.path.join(app.root_path, 'templates', 'index.html'))}")
    print(f"📊 Products: {len(db.products)}")
    print(f"📊 Sales: {len(db.sales)}")
    print(f"🌐 Port: {port}")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)
