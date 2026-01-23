from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from functools import wraps
import json
import os
import datetime
from collections import defaultdict
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'KSS@2026_SECRET_KEY'  # Change this in production

# File paths
PRODUCTS_FILE = 'data/products.json'
SALES_FILE = 'data/sales.json'
USERS_FILE = 'data/users.json'

# Admin credentials
ADMIN_USERNAME = "KSS@2026"
ADMIN_PASSWORD = "KSS@$$$"

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Load data from files
def load_products():
    try:
        with open(PRODUCTS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Default products
        default_products = [
            {
                "id": 1,
                "name": "Men's Running Shoes",
                "description": "Lightweight running shoes with superior cushioning",
                "price": 4500,
                "original_price": 5500,
                "image": "https://images.unsplash.com/photo-1549298916-b41d501d3772?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=500&q=80",
                "category": "men",
                "stock": 15,
                "created_at": "2026-01-01"
            },
            {
                "id": 2,
                "name": "Women's Casual Sneakers",
                "description": "Comfortable and stylish sneakers for everyday wear",
                "price": 3800,
                "original_price": 4500,
                "image": "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=500&q=80",
                "category": "women",
                "stock": 20,
                "created_at": "2026-01-01"
            },
            {
                "id": 3,
                "name": "Men's Formal Shoes",
                "description": "Classic leather formal shoes for business occasions",
                "price": 6200,
                "original_price": 7500,
                "image": "https://images.unsplash.com/photo-1595341888016-a392ef81b7de?ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D&auto=format&fit=crop&w=500&q=80",
                "category": "men",
                "stock": 8,
                "created_at": "2026-01-01"
            }
        ]
        save_products(default_products)
        return default_products

def save_products(products):
    with open(PRODUCTS_FILE, 'w') as f:
        json.dump(products, f, indent=2)

def load_sales():
    try:
        with open(SALES_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Default empty sales
        default_sales = []
        save_sales(default_sales)
        return default_sales

def save_sales(sales):
    with open(SALES_FILE, 'w') as f:
        json.dump(sales, f, indent=2)

def load_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # Default admin user
        default_users = [
            {
                "username": ADMIN_USERNAME,
                "password": ADMIN_PASSWORD,
                "role": "admin",
                "created_at": "2026-01-01"
            }
        ]
        save_users(default_users)
        return default_users

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/')
def index():
    return send_file('index.html')

@app.route('/admin')
def admin_login_page():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    return render_template('admin.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({"success": True, "message": "Login successful"})
    
    return jsonify({"success": False, "message": "Invalid credentials"}), 401

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_login_page'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    return render_template('admin.html')

# API Routes for admin
@app.route('/api/admin/products', methods=['GET'])
@admin_required
def get_products():
    products = load_products()
    return jsonify(products)

@app.route('/api/admin/products', methods=['POST'])
@admin_required
def add_product():
    try:
        products = load_products()
        
        # Get the next ID
        next_id = max([p['id'] for p in products], default=0) + 1
        
        data = request.get_json()
        
        new_product = {
            "id": next_id,
            "name": data['name'],
            "description": data['description'],
            "price": float(data['price']),
            "original_price": float(data.get('original_price', data['price'])),
            "image": data.get('image', ''),
            "category": data['category'],
            "stock": int(data['stock']),
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d")
        }
        
        products.append(new_product)
        save_products(products)
        
        return jsonify({"success": True, "product": new_product})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@admin_required
def update_product(product_id):
    try:
        products = load_products()
        
        for i, product in enumerate(products):
            if product['id'] == product_id:
                data = request.get_json()
                
                products[i].update({
                    "name": data.get('name', product['name']),
                    "description": data.get('description', product['description']),
                    "price": float(data.get('price', product['price'])),
                    "original_price": float(data.get('original_price', product.get('original_price', product['price']))),
                    "image": data.get('image', product.get('image', '')),
                    "category": data.get('category', product['category']),
                    "stock": int(data.get('stock', product['stock']))
                })
                
                save_products(products)
                return jsonify({"success": True, "product": products[i]})
        
        return jsonify({"success": False, "message": "Product not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    try:
        products = load_products()
        
        for i, product in enumerate(products):
            if product['id'] == product_id:
                deleted_product = products.pop(i)
                save_products(products)
                return jsonify({"success": True, "message": "Product deleted"})
        
        return jsonify({"success": False, "message": "Product not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/api/admin/sales', methods=['GET'])
@admin_required
def get_sales():
    sales = load_sales()
    return jsonify(sales)

@app.route('/api/admin/sales', methods=['POST'])
def add_sale():
    try:
        data = request.get_json()
        sales = load_sales()
        
        # Generate sale ID
        next_id = max([s['id'] for s in sales], default=0) + 1
        
        new_sale = {
            "id": next_id,
            "customer_name": data.get('customer_name', 'Walk-in Customer'),
            "customer_phone": data.get('customer_phone', ''),
            "items": data['items'],
            "subtotal": float(data['subtotal']),
            "shipping": float(data.get('shipping', 0)),
            "total": float(data['total']),
            "payment_method": data.get('payment_method', 'Cash'),
            "status": data.get('status', 'Completed'),
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Update product stock
        products = load_products()
        for sale_item in data['items']:
            for product in products:
                if product['id'] == sale_item['id']:
                    product['stock'] -= sale_item['quantity']
                    break
        
        save_products(products)
        
        sales.append(new_sale)
        save_sales(sales)
        
        return jsonify({"success": True, "sale": new_sale})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def get_stats():
    products = load_products()
    sales = load_sales()
    
    # Calculate statistics
    total_products = len(products)
    total_sales = len(sales)
    
    # Calculate total revenue
    total_revenue = sum(sale['total'] for sale in sales)
    
    # Calculate low stock items (less than 5)
    low_stock = [p for p in products if p['stock'] < 5]
    
    # Calculate monthly sales
    monthly_sales = defaultdict(float)
    for sale in sales:
        month = sale['date'][:7]  # YYYY-MM
        monthly_sales[month] += sale['total']
    
    # Top selling products
    product_sales = defaultdict(int)
    for sale in sales:
        for item in sale['items']:
            product_sales[item['name']] += item['quantity']
    
    top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    
    return jsonify({
        "total_products": total_products,
        "total_sales": total_sales,
        "total_revenue": total_revenue,
        "low_stock_count": len(low_stock),
        "low_stock": low_stock,
        "monthly_sales": dict(monthly_sales),
        "top_products": [{"name": name, "quantity": qty} for name, qty in top_products]
    })

@app.route('/api/admin/export/sales', methods=['GET'])
@admin_required
def export_sales():
    sales = load_sales()
    
    # Create CSV string
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header
    writer.writerow(['Sale ID', 'Date', 'Customer Name', 'Customer Phone', 'Items', 'Subtotal', 'Shipping', 'Total', 'Payment Method', 'Status'])
    
    # Write data
    for sale in sales:
        items_str = '; '.join([f"{item['name']} x{item['quantity']}" for item in sale['items']])
        writer.writerow([
            sale['id'],
            sale['date'],
            sale['customer_name'],
            sale['customer_phone'],
            items_str,
            sale['subtotal'],
            sale['shipping'],
            sale['total'],
            sale['payment_method'],
            sale['status']
        ])
    
    output.seek(0)
    
    # Create response with CSV file
    return send_file(
        StringIO(output.getvalue()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'sales_export_{datetime.datetime.now().strftime("%Y%m%d")}.csv'
    )

# API for frontend
@app.route('/api/products', methods=['GET'])
def api_get_products():
    products = load_products()
    return jsonify(products)

# Static file serving
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# Admin template
@app.route('/admin-template')
def admin_template():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Karanja Shoe Store - Admin Panel</title>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
                font-family: 'Poppins', sans-serif;
            }

            :root {
                --primary: #2c3e50;
                --secondary: #e74c3c;
                --accent: #f39c12;
                --light: #ecf0f1;
                --dark: #2c3e50;
                --gray: #95a5a6;
            }

            body {
                background-color: #f5f7fa;
                color: #333;
            }

            .admin-container {
                display: flex;
                min-height: 100vh;
            }

            /* Sidebar */
            .sidebar {
                width: 250px;
                background-color: var(--primary);
                color: white;
                padding: 20px 0;
                position: fixed;
                height: 100vh;
                overflow-y: auto;
            }

            .logo {
                padding: 0 20px 20px;
                border-bottom: 1px solid rgba(255,255,255,0.1);
                margin-bottom: 20px;
            }

            .logo h2 {
                display: flex;
                align-items: center;
                color: white;
            }

            .logo i {
                color: var(--accent);
                margin-right: 10px;
            }

            .logo span {
                color: var(--accent);
            }

            .nav-menu {
                list-style: none;
            }

            .nav-menu li {
                margin-bottom: 5px;
            }

            .nav-menu a {
                display: flex;
                align-items: center;
                padding: 12px 20px;
                color: rgba(255,255,255,0.8);
                text-decoration: none;
                transition: all 0.3s;
            }

            .nav-menu a:hover, .nav-menu a.active {
                background-color: rgba(255,255,255,0.1);
                color: white;
                border-left: 4px solid var(--accent);
            }

            .nav-menu i {
                margin-right: 10px;
                width: 20px;
                text-align: center;
            }

            /* Main Content */
            .main-content {
                flex: 1;
                margin-left: 250px;
                padding: 20px;
            }

            .header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding-bottom: 20px;
                border-bottom: 1px solid #ddd;
                margin-bottom: 30px;
            }

            .header h1 {
                color: var(--primary);
                font-size: 28px;
            }

            .user-info {
                display: flex;
                align-items: center;
            }

            .user-info span {
                margin-right: 15px;
                color: var(--primary);
            }

            .logout-btn {
                background-color: var(--secondary);
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                cursor: pointer;
                transition: background-color 0.3s;
            }

            .logout-btn:hover {
                background-color: #c0392b;
            }

            /* Stats Cards */
            .stats-cards {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 20px;
                margin-bottom: 30px;
            }

            .stat-card {
                background-color: white;
                padding: 25px;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.05);
                display: flex;
                align-items: center;
            }

            .stat-icon {
                width: 60px;
                height: 60px;
                border-radius: 10px;
                display: flex;
                justify-content: center;
                align-items: center;
                font-size: 24px;
                margin-right: 20px;
            }

            .stat-icon.sales {
                background-color: rgba(46, 204, 113, 0.2);
                color: #2ecc71;
            }

            .stat-icon.revenue {
                background-color: rgba(52, 152, 219, 0.2);
                color: #3498db;
            }

            .stat-icon.products {
                background-color: rgba(155, 89, 182, 0.2);
                color: #9b59b6;
            }

            .stat-icon.stock {
                background-color: rgba(241, 196, 15, 0.2);
                color: #f1c40f;
            }

            .stat-info h3 {
                font-size: 14px;
                color: var(--gray);
                margin-bottom: 5px;
            }

            .stat-info .value {
                font-size: 28px;
                font-weight: 700;
                color: var(--primary);
            }

            /* Content Sections */
            .content-section {
                background-color: white;
                border-radius: 10px;
                box-shadow: 0 5px 15px rgba(0,0,0,0.05);
                padding: 25px;
                margin-bottom: 30px;
            }

            .section-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
                padding-bottom: 15px;
                border-bottom: 1px solid #eee;
            }

            .section-header h2 {
                color: var(--primary);
                font-size: 22px;
            }

            .btn {
                background-color: var(--primary);
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                transition: all 0.3s;
                font-weight: 500;
                display: inline-flex;
                align-items: center;
            }

            .btn:hover {
                background-color: #1a252f;
                transform: translateY(-2px);
            }

            .btn i {
                margin-right: 8px;
            }

            .btn-success {
                background-color: #2ecc71;
            }

            .btn-success:hover {
                background-color: #27ae60;
            }

            .btn-danger {
                background-color: #e74c3c;
            }

            .btn-danger:hover {
                background-color: #c0392b;
            }

            /* Tables */
            .table-container {
                overflow-x: auto;
            }

            table {
                width: 100%;
                border-collapse: collapse;
            }

            table th {
                background-color: #f8f9fa;
                padding: 15px;
                text-align: left;
                font-weight: 600;
                color: var(--primary);
                border-bottom: 2px solid #eee;
            }

            table td {
                padding: 15px;
                border-bottom: 1px solid #eee;
            }

            table tr:hover {
                background-color: #f8f9fa;
            }

            .action-btns {
                display: flex;
                gap: 10px;
            }

            .action-btn {
                width: 35px;
                height: 35px;
                border-radius: 5px;
                display: flex;
                justify-content: center;
                align-items: center;
                cursor: pointer;
                border: none;
                transition: all 0.3s;
            }

            .edit-btn {
                background-color: rgba(52, 152, 219, 0.1);
                color: #3498db;
            }

            .edit-btn:hover {
                background-color: #3498db;
                color: white;
            }

            .delete-btn {
                background-color: rgba(231, 76, 60, 0.1);
                color: #e74c3c;
            }

            .delete-btn:hover {
                background-color: #e74c3c;
                color: white;
            }

            /* Forms */
            .form-group {
                margin-bottom: 20px;
            }

            .form-group label {
                display: block;
                margin-bottom: 8px;
                font-weight: 500;
                color: var(--primary);
            }

            .form-control {
                width: 100%;
                padding: 12px 15px;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
                transition: border-color 0.3s;
            }

            .form-control:focus {
                border-color: var(--primary);
                outline: none;
            }

            .form-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
            }

            /* Modal */
            .modal {
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background-color: rgba(0,0,0,0.5);
                z-index: 1000;
                justify-content: center;
                align-items: center;
            }

            .modal-content {
                background-color: white;
                width: 90%;
                max-width: 700px;
                border-radius: 10px;
                overflow: hidden;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            }

            .modal-header {
                padding: 20px;
                background-color: var(--primary);
                color: white;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .modal-header h3 {
                font-size: 20px;
            }

            .close-modal {
                background: none;
                border: none;
                color: white;
                font-size: 24px;
                cursor: pointer;
            }

            .modal-body {
                padding: 30px;
                max-height: 70vh;
                overflow-y: auto;
            }

            .modal-footer {
                padding: 20px;
                background-color: #f8f9fa;
                display: flex;
                justify-content: flex-end;
                gap: 10px;
            }

            /* Login Page */
            .login-container {
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                background-color: var(--primary);
            }

            .login-box {
                background-color: white;
                width: 90%;
                max-width: 400px;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 10px 30px rgba(0,0,0,0.2);
                text-align: center;
            }

            .login-logo {
                margin-bottom: 30px;
            }

            .login-logo h2 {
                color: var(--primary);
                display: flex;
                justify-content: center;
                align-items: center;
            }

            .login-logo i {
                color: var(--accent);
                margin-right: 10px;
            }

            .login-logo span {
                color: var(--accent);
            }

            .login-form .form-group {
                margin-bottom: 25px;
                text-align: left;
            }

            .login-btn {
                width: 100%;
                padding: 15px;
                font-size: 16px;
                margin-top: 10px;
            }

            .alert {
                padding: 15px;
                border-radius: 5px;
                margin-bottom: 20px;
                display: none;
            }

            .alert-success {
                background-color: rgba(46, 204, 113, 0.2);
                color: #27ae60;
                border-left: 4px solid #2ecc71;
            }

            .alert-error {
                background-color: rgba(231, 76, 60, 0.2);
                color: #c0392b;
                border-left: 4px solid #e74c3c;
            }

            /* Chart */
            .chart-container {
                height: 300px;
                margin-top: 20px;
            }

            /* Responsive */
            @media (max-width: 992px) {
                .sidebar {
                    width: 70px;
                }

                .sidebar .logo h2 span,
                .sidebar .nav-menu a span {
                    display: none;
                }

                .sidebar .logo h2 {
                    justify-content: center;
                }

                .sidebar .nav-menu a {
                    justify-content: center;
                }

                .sidebar .nav-menu i {
                    margin-right: 0;
                    font-size: 20px;
                }

                .main-content {
                    margin-left: 70px;
                }
            }

            @media (max-width: 768px) {
                .stats-cards {
                    grid-template-columns: 1fr;
                }

                .form-row {
                    grid-template-columns: 1fr;
                }

                .action-btns {
                    flex-direction: column;
                }
            }
        </style>
    </head>
    <body>
        <!-- Login Page -->
        <div id="loginPage" class="login-container">
            <div class="login-box">
                <div class="login-logo">
                    <h2><i class="fas fa-shoe-prints"></i> <span>Karanja</span> Admin</h2>
                    <p>Karanja Shoe Store Administration</p>
                </div>
                
                <div class="alert" id="loginAlert"></div>
                
                <form class="login-form" id="loginForm">
                    <div class="form-group">
                        <label for="username">Username</label>
                        <input type="text" id="username" class="form-control" placeholder="Enter username" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="password">Password</label>
                        <input type="password" id="password" class="form-control" placeholder="Enter password" required>
                    </div>
                    
                    <button type="submit" class="btn login-btn">
                        <i class="fas fa-sign-in-alt"></i> Login
                    </button>
                </form>
                
                <div style="margin-top: 20px; font-size: 14px; color: #666;">
                    <p>Default credentials: Username: <strong>KSS@2026</strong>, Password: <strong>KSS@$$$</strong></p>
                </div>
            </div>
        </div>
        
        <!-- Admin Dashboard -->
        <div id="adminDashboard" class="admin-container" style="display: none;">
            <!-- Sidebar -->
            <div class="sidebar">
                <div class="logo">
                    <h2><i class="fas fa-shoe-prints"></i> <span>Karanja</span> Admin</h2>
                </div>
                
                <ul class="nav-menu">
                    <li><a href="#" class="active" data-section="dashboard"><i class="fas fa-tachometer-alt"></i> <span>Dashboard</span></a></li>
                    <li><a href="#" data-section="products"><i class="fas fa-shopping-bag"></i> <span>Products</span></a></li>
                    <li><a href="#" data-section="sales"><i class="fas fa-chart-line"></i> <span>Sales</span></a></li>
                    <li><a href="#" data-section="addProduct"><i class="fas fa-plus-circle"></i> <span>Add Product</span></a></li>
                    <li><a href="#" data-section="analytics"><i class="fas fa-chart-pie"></i> <span>Analytics</span></a></li>
                </ul>
            </div>
            
            <!-- Main Content -->
            <div class="main-content">
                <div class="header">
                    <h1 id="pageTitle">Dashboard</h1>
                    <div class="user-info">
                        <span id="adminUsername">Administrator</span>
                        <button class="logout-btn" id="logoutBtn"><i class="fas fa-sign-out-alt"></i> Logout</button>
                    </div>
                </div>
                
                <!-- Dashboard Section -->
                <div id="dashboardSection" class="content-section">
                    <div class="stats-cards" id="statsCards">
                        <!-- Stats will be loaded here -->
                    </div>
                    
                    <div class="section-header">
                        <h2>Recent Sales</h2>
                        <button class="btn" id="exportSalesBtn"><i class="fas fa-download"></i> Export Sales</button>
                    </div>
                    
                    <div class="table-container">
                        <table id="recentSalesTable">
                            <thead>
                                <tr>
                                    <th>Sale ID</th>
                                    <th>Date</th>
                                    <th>Customer</th>
                                    <th>Items</th>
                                    <th>Total</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody id="recentSalesBody">
                                <!-- Recent sales will be loaded here -->
                            </tbody>
                        </table>
                    </div>
                    
                    <div class="section-header" style="margin-top: 30px;">
                        <h2>Low Stock Alert</h2>
                    </div>
                    
                    <div class="table-container">
                        <table id="lowStockTable">
                            <thead>
                                <tr>
                                    <th>Product</th>
                                    <th>Category</th>
                                    <th>Current Stock</th>
                                    <th>Price</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody id="lowStockBody">
                                <!-- Low stock products will be loaded here -->
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <!-- Products Section -->
                <div id="productsSection" class="content-section" style="display: none;">
                    <div class="section-header">
                        <h2>All Products</h2>
                        <button class="btn" id="addNewProductBtn"><i class="fas fa-plus"></i> Add New Product</button>
                    </div>
                    
                    <div class="table-container">
                        <table id="productsTable">
                            <thead>
                                <tr>
                                    <th>ID</th>
                                    <th>Image</th>
                                    <th>Product Name</th>
                                    <th>Category</th>
                                    <th>Price</th>
                                    <th>Stock</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody id="productsBody">
                                <!-- Products will be loaded here -->
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <!-- Sales Section -->
                <div id="salesSection" class="content-section" style="display: none;">
                    <div class="section-header">
                        <h2>Sales Records</h2>
                        <button class="btn" id="exportAllSalesBtn"><i class="fas fa-download"></i> Export All Sales</button>
                    </div>
                    
                    <div class="table-container">
                        <table id="salesTable">
                            <thead>
                                <tr>
                                    <th>Sale ID</th>
                                    <th>Date</th>
                                    <th>Customer</th>
                                    <th>Phone</th>
                                    <th>Items</th>
                                    <th>Subtotal</th>
                                    <th>Total</th>
                                    <th>Payment</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody id="salesBody">
                                <!-- Sales will be loaded here -->
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <!-- Add Product Section -->
                <div id="addProductSection" class="content-section" style="display: none;">
                    <div class="section-header">
                        <h2>Add New Product</h2>
                    </div>
                    
                    <form id="productForm">
                        <div class="form-row">
                            <div class="form-group">
                                <label for="productName">Product Name</label>
                                <input type="text" id="productName" class="form-control" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="productCategory">Category</label>
                                <select id="productCategory" class="form-control" required>
                                    <option value="">Select Category</option>
                                    <option value="men">Men</option>
                                    <option value="women">Women</option>
                                    <option value="kids">Kids</option>
                                    <option value="unisex">Unisex</option>
                                </select>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="productDescription">Description</label>
                            <textarea id="productDescription" class="form-control" rows="3" required></textarea>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="productPrice">Price (Ksh)</label>
                                <input type="number" id="productPrice" class="form-control" min="0" step="0.01" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="originalPrice">Original Price (Ksh) - Optional</label>
                                <input type="number" id="originalPrice" class="form-control" min="0" step="0.01">
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="productStock">Stock Quantity</label>
                                <input type="number" id="productStock" class="form-control" min="0" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="productImage">Image URL</label>
                                <input type="text" id="productImage" class="form-control" placeholder="https://example.com/image.jpg">
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <button type="submit" class="btn btn-success" id="saveProductBtn">
                                <i class="fas fa-save"></i> Save Product
                            </button>
                            <button type="button" class="btn" id="cancelProductBtn">Cancel</button>
                        </div>
                    </form>
                </div>
                
                <!-- Analytics Section -->
                <div id="analyticsSection" class="content-section" style="display: none;">
                    <div class="section-header">
                        <h2>Sales Analytics</h2>
                        <div>
                            <select id="timeRange" class="form-control" style="width: auto; display: inline-block;">
                                <option value="monthly">Monthly</option>
                                <option value="weekly">Weekly</option>
                                <option value="yearly">Yearly</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="chart-container">
                        <canvas id="salesChart"></canvas>
                    </div>
                    
                    <div class="section-header" style="margin-top: 30px;">
                        <h2>Top Selling Products</h2>
                    </div>
                    
                    <div class="table-container">
                        <table id="topProductsTable">
                            <thead>
                                <tr>
                                    <th>Product</th>
                                    <th>Quantity Sold</th>
                                    <th>Revenue</th>
                                    <th>Category</th>
                                </tr>
                            </thead>
                            <tbody id="topProductsBody">
                                <!-- Top products will be loaded here -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Edit Product Modal -->
        <div id="editProductModal" class="modal">
            <div class="modal-content">
                <div class="modal-header">
                    <h3>Edit Product</h3>
                    <button class="close-modal" id="closeEditModal">&times;</button>
                </div>
                <div class="modal-body">
                    <form id="editProductForm">
                        <input type="hidden" id="editProductId">
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editProductName">Product Name</label>
                                <input type="text" id="editProductName" class="form-control" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="editProductCategory">Category</label>
                                <select id="editProductCategory" class="form-control" required>
                                    <option value="">Select Category</option>
                                    <option value="men">Men</option>
                                    <option value="women">Women</option>
                                    <option value="kids">Kids</option>
                                    <option value="unisex">Unisex</option>
                                </select>
                            </div>
                        </div>
                        
                        <div class="form-group">
                            <label for="editProductDescription">Description</label>
                            <textarea id="editProductDescription" class="form-control" rows="3" required></textarea>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editProductPrice">Price (Ksh)</label>
                                <input type="number" id="editProductPrice" class="form-control" min="0" step="0.01" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="editOriginalPrice">Original Price (Ksh) - Optional</label>
                                <input type="number" id="editOriginalPrice" class="form-control" min="0" step="0.01">
                            </div>
                        </div>
                        
                        <div class="form-row">
                            <div class="form-group">
                                <label for="editProductStock">Stock Quantity</label>
                                <input type="number" id="editProductStock" class="form-control" min="0" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="editProductImage">Image URL</label>
                                <input type="text" id="editProductImage" class="form-control">
                            </div>
                        </div>
                    </form>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-success" id="updateProductBtn">Update Product</button>
                    <button class="btn" id="closeEditModalBtn">Cancel</button>
                </div>
            </div>
        </div>
        
        <!-- Alert Modal -->
        <div id="alertModal" class="modal">
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h3 id="alertTitle">Alert</h3>
                    <button class="close-modal" id="closeAlertModal">&times;</button>
                </div>
                <div class="modal-body">
                    <p id="alertMessage"></p>
                </div>
                <div class="modal-footer">
                    <button class="btn" id="confirmAlertBtn">OK</button>
                </div>
            </div>
        </div>
        
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
            // Global variables
            let currentProductId = null;
            let salesChart = null;
            
            // DOM Elements
            const loginPage = document.getElementById('loginPage');
            const adminDashboard = document.getElementById('adminDashboard');
            const loginForm = document.getElementById('loginForm');
            const loginAlert = document.getElementById('loginAlert');
            const logoutBtn = document.getElementById('logoutBtn');
            const adminUsername = document.getElementById('adminUsername');
            const pageTitle = document.getElementById('pageTitle');
            
            // Section elements
            const dashboardSection = document.getElementById('dashboardSection');
            const productsSection = document.getElementById('productsSection');
            const salesSection = document.getElementById('salesSection');
            const addProductSection = document.getElementById('addProductSection');
            const analyticsSection = document.getElementById('analyticsSection');
            
            // Modal elements
            const editProductModal = document.getElementById('editProductModal');
            const alertModal = document.getElementById('alertModal');
            
            // Check if user is already logged in
            function checkLogin() {
                fetch('/api/admin/stats')
                    .then(response => {
                        if (response.ok) {
                            // User is logged in
                            loginPage.style.display = 'none';
                            adminDashboard.style.display = 'flex';
                            loadDashboard();
                        } else {
                            // User is not logged in
                            loginPage.style.display = 'flex';
                            adminDashboard.style.display = 'none';
                        }
                    })
                    .catch(() => {
                        loginPage.style.display = 'flex';
                        adminDashboard.style.display = 'none';
                    });
            }
            
            // Login function
            loginForm.addEventListener('submit', function(e) {
                e.preventDefault();
                
                const username = document.getElementById('username').value;
                const password = document.getElementById('password').value;
                
                fetch('/admin/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username, password })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        loginPage.style.display = 'none';
                        adminDashboard.style.display = 'flex';
                        adminUsername.textContent = username;
                        loadDashboard();
                    } else {
                        showAlert('Invalid username or password', 'error');
                    }
                })
                .catch(() => {
                    showAlert('Login failed. Please try again.', 'error');
                });
            });
            
            // Logout function
            logoutBtn.addEventListener('click', function() {
                fetch('/admin/logout')
                    .then(() => {
                        loginPage.style.display = 'flex';
                        adminDashboard.style.display = 'none';
                        document.getElementById('username').value = '';
                        document.getElementById('password').value = '';
                    });
            });
            
            // Navigation
            document.querySelectorAll('.nav-menu a').forEach(link => {
                link.addEventListener('click', function(e) {
                    e.preventDefault();
                    
                    // Update active link
                    document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
                    this.classList.add('active');
                    
                    // Get section to show
                    const section = this.getAttribute('data-section');
                    
                    // Hide all sections
                    dashboardSection.style.display = 'none';
                    productsSection.style.display = 'none';
                    salesSection.style.display = 'none';
                    addProductSection.style.display = 'none';
                    analyticsSection.style.display = 'none';
                    
                    // Show selected section
                    switch(section) {
                        case 'dashboard':
                            dashboardSection.style.display = 'block';
                            pageTitle.textContent = 'Dashboard';
                            loadDashboard();
                            break;
                        case 'products':
                            productsSection.style.display = 'block';
                            pageTitle.textContent = 'Products';
                            loadProducts();
                            break;
                        case 'sales':
                            salesSection.style.display = 'block';
                            pageTitle.textContent = 'Sales Records';
                            loadSales();
                            break;
                        case 'addProduct':
                            addProductSection.style.display = 'block';
                            pageTitle.textContent = 'Add Product';
                            break;
                        case 'analytics':
                            analyticsSection.style.display = 'block';
                            pageTitle.textContent = 'Analytics';
                            loadAnalytics();
                            break;
                    }
                });
            });
            
            // Load dashboard data
            function loadDashboard() {
                // Load stats
                fetch('/api/admin/stats')
                    .then(response => response.json())
                    .then(data => {
                        // Update stats cards
                        const statsCards = document.getElementById('statsCards');
                        statsCards.innerHTML = `
                            <div class="stat-card">
                                <div class="stat-icon sales">
                                    <i class="fas fa-chart-line"></i>
                                </div>
                                <div class="stat-info">
                                    <h3>Total Sales</h3>
                                    <div class="value">${data.total_sales}</div>
                                </div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-icon revenue">
                                    <i class="fas fa-money-bill-wave"></i>
                                </div>
                                <div class="stat-info">
                                    <h3>Total Revenue</h3>
                                    <div class="value">Ksh ${data.total_revenue.toLocaleString()}</div>
                                </div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-icon products">
                                    <i class="fas fa-shopping-bag"></i>
                                </div>
                                <div class="stat-info">
                                    <h3>Total Products</h3>
                                    <div class="value">${data.total_products}</div>
                                </div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-icon stock">
                                    <i class="fas fa-exclamation-triangle"></i>
                                </div>
                                <div class="stat-info">
                                    <h3>Low Stock Items</h3>
                                    <div class="value">${data.low_stock_count}</div>
                                </div>
                            </div>
                        `;
                        
                        // Load recent sales
                        fetch('/api/admin/sales')
                            .then(response => response.json())
                            .then(sales => {
                                const recentSales = sales.slice(-10).reverse(); // Last 10 sales
                                const recentSalesBody = document.getElementById('recentSalesBody');
                                recentSalesBody.innerHTML = '';
                                
                                recentSales.forEach(sale => {
                                    const itemsText = sale.items.map(item => `${item.name} x${item.quantity}`).join(', ');
                                    const row = document.createElement('tr');
                                    row.innerHTML = `
                                        <td>#${sale.id}</td>
                                        <td>${sale.date}</td>
                                        <td>${sale.customer_name}</td>
                                        <td>${itemsText}</td>
                                        <td>Ksh ${sale.total.toLocaleString()}</td>
                                        <td><span style="color: ${sale.status === 'Completed' ? '#2ecc71' : '#e74c3c'}">${sale.status}</span></td>
                                    `;
                                    recentSalesBody.appendChild(row);
                                });
                            });
                        
                        // Load low stock products
                        const lowStockBody = document.getElementById('lowStockBody');
                        lowStockBody.innerHTML = '';
                        
                        if (data.low_stock && data.low_stock.length > 0) {
                            data.low_stock.forEach(product => {
                                const row = document.createElement('tr');
                                row.innerHTML = `
                                    <td>${product.name}</td>
                                    <td>${product.category}</td>
                                    <td><span style="color: #e74c3c; font-weight: bold;">${product.stock}</span></td>
                                    <td>Ksh ${product.price.toLocaleString()}</td>
                                    <td>
                                        <button class="action-btn edit-btn" onclick="editProduct(${product.id})">
                                            <i class="fas fa-edit"></i>
                                        </button>
                                    </td>
                                `;
                                lowStockBody.appendChild(row);
                            });
                        } else {
                            const row = document.createElement('tr');
                            row.innerHTML = `<td colspan="5" style="text-align: center;">No low stock items</td>`;
                            lowStockBody.appendChild(row);
                        }
                    });
            }
            
            // Load products
            function loadProducts() {
                fetch('/api/admin/products')
                    .then(response => response.json())
                    .then(products => {
                        const productsBody = document.getElementById('productsBody');
                        productsBody.innerHTML = '';
                        
                        products.forEach(product => {
                            const row = document.createElement('tr');
                            row.innerHTML = `
                                <td>${product.id}</td>
                                <td><img src="${product.image}" alt="${product.name}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 5px;"></td>
                                <td>${product.name}</td>
                                <td>${product.category}</td>
                                <td>Ksh ${product.price.toLocaleString()}</td>
                                <td>${product.stock}</td>
                                <td>
                                    <div class="action-btns">
                                        <button class="action-btn edit-btn" onclick="editProduct(${product.id})">
                                            <i class="fas fa-edit"></i>
                                        </button>
                                        <button class="action-btn delete-btn" onclick="deleteProduct(${product.id})">
                                            <i class="fas fa-trash"></i>
                                        </button>
                                    </div>
                                </td>
                            `;
                            productsBody.appendChild(row);
                        });
                    });
            }
            
            // Load sales
            function loadSales() {
                fetch('/api/admin/sales')
                    .then(response => response.json())
                    .then(sales => {
                        const salesBody = document.getElementById('salesBody');
                        salesBody.innerHTML = '';
                        
                        // Reverse to show latest first
                        sales.reverse().forEach(sale => {
                            const itemsText = sale.items.map(item => `${item.name} x${item.quantity}`).join('; ');
                            const row = document.createElement('tr');
                            row.innerHTML = `
                                <td>#${sale.id}</td>
                                <td>${sale.date}</td>
                                <td>${sale.customer_name}</td>
                                <td>${sale.customer_phone}</td>
                                <td>${itemsText}</td>
                                <td>Ksh ${sale.subtotal.toLocaleString()}</td>
                                <td>Ksh ${sale.total.toLocaleString()}</td>
                                <td>${sale.payment_method}</td>
                                <td><span style="color: ${sale.status === 'Completed' ? '#2ecc71' : '#e74c3c'}">${sale.status}</span></td>
                            `;
                            salesBody.appendChild(row);
                        });
                    });
            }
            
            // Load analytics
            function loadAnalytics() {
                fetch('/api/admin/stats')
                    .then(response => response.json())
                    .then(data => {
                        // Load top products
                        const topProductsBody = document.getElementById('topProductsBody');
                        topProductsBody.innerHTML = '';
                        
                        if (data.top_products && data.top_products.length > 0) {
                            data.top_products.forEach(product => {
                                // Calculate revenue (need to get price from products)
                                fetch('/api/admin/products')
                                    .then(response => response.json())
                                    .then(products => {
                                        const prod = products.find(p => p.name === product.name);
                                        const revenue = prod ? prod.price * product.quantity : 0;
                                        
                                        const row = document.createElement('tr');
                                        row.innerHTML = `
                                            <td>${product.name}</td>
                                            <td>${product.quantity}</td>
                                            <td>Ksh ${revenue.toLocaleString()}</td>
                                            <td>${prod ? prod.category : 'N/A'}</td>
                                        `;
                                        topProductsBody.appendChild(row);
                                    });
                            });
                        } else {
                            const row = document.createElement('tr');
                            row.innerHTML = `<td colspan="4" style="text-align: center;">No sales data available</td>`;
                            topProductsBody.appendChild(row);
                        }
                        
                        // Load chart data
                        const monthlySales = data.monthly_sales || {};
                        const months = Object.keys(monthlySales).sort();
                        const salesData = months.map(month => monthlySales[month]);
                        
                        // Create or update chart
                        const ctx = document.getElementById('salesChart').getContext('2d');
                        
                        if (salesChart) {
                            salesChart.destroy();
                        }
                        
                        salesChart = new Chart(ctx, {
                            type: 'line',
                            data: {
                                labels: months,
                                datasets: [{
                                    label: 'Monthly Revenue (Ksh)',
                                    data: salesData,
                                    borderColor: '#3498db',
                                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                                    borderWidth: 2,
                                    fill: true
                                }]
                            },
                            options: {
                                responsive: true,
                                maintainAspectRatio: false,
                                scales: {
                                    y: {
                                        beginAtZero: true,
                                        ticks: {
                                            callback: function(value) {
                                                return 'Ksh ' + value.toLocaleString();
                                            }
                                        }
                                    }
                                }
                            }
                        });
                    });
            }
            
            // Add new product
            document.getElementById('addNewProductBtn')?.addEventListener('click', function() {
                // Navigate to add product section
                document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
                document.querySelector('.nav-menu a[data-section="addProduct"]').classList.add('active');
                
                dashboardSection.style.display = 'none';
                productsSection.style.display = 'none';
                salesSection.style.display = 'none';
                addProductSection.style.display = 'block';
                analyticsSection.style.display = 'none';
                pageTitle.textContent = 'Add Product';
            });
            
            // Save product
            document.getElementById('productForm')?.addEventListener('submit', function(e) {
                e.preventDefault();
                
                const productData = {
                    name: document.getElementById('productName').value,
                    description: document.getElementById('productDescription').value,
                    price: parseFloat(document.getElementById('productPrice').value),
                    original_price: document.getElementById('originalPrice').value ? 
                        parseFloat(document.getElementById('originalPrice').value) : 
                        parseFloat(document.getElementById('productPrice').value),
                    image: document.getElementById('productImage').value,
                    category: document.getElementById('productCategory').value,
                    stock: parseInt(document.getElementById('productStock').value)
                };
                
                fetch('/api/admin/products', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(productData)
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        // Reset form
                        document.getElementById('productForm').reset();
                        
                        // Show success message
                        showAlert('Product added successfully!', 'success');
                        
                        // Navigate to products section
                        document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
                        document.querySelector('.nav-menu a[data-section="products"]').classList.add('active');
                        
                        dashboardSection.style.display = 'none';
                        productsSection.style.display = 'block';
                        addProductSection.style.display = 'none';
                        salesSection.style.display = 'none';
                        analyticsSection.style.display = 'none';
                        pageTitle.textContent = 'Products';
                        
                        // Reload products
                        loadProducts();
                    } else {
                        showAlert('Failed to add product: ' + data.message, 'error');
                    }
                })
                .catch(() => {
                    showAlert('Failed to add product. Please try again.', 'error');
                });
            });
            
            // Cancel adding product
            document.getElementById('cancelProductBtn')?.addEventListener('click', function() {
                document.getElementById('productForm').reset();
                
                // Navigate to products section
                document.querySelectorAll('.nav-menu a').forEach(a => a.classList.remove('active'));
                document.querySelector('.nav-menu a[data-section="products"]').classList.add('active');
                
                dashboardSection.style.display = 'none';
                productsSection.style.display = 'block';
                addProductSection.style.display = 'none';
                salesSection.style.display = 'none';
                analyticsSection.style.display = 'none';
                pageTitle.textContent = 'Products';
            });
            
            // Edit product
            window.editProduct = function(productId) {
                currentProductId = productId;
                
                fetch('/api/admin/products')
                    .then(response => response.json())
                    .then(products => {
                        const product = products.find(p => p.id === productId);
                        
                        if (product) {
                            document.getElementById('editProductId').value = product.id;
                            document.getElementById('editProductName').value = product.name;
                            document.getElementById('editProductDescription').value = product.description;
                            document.getElementById('editProductPrice').value = product.price;
                            document.getElementById('editOriginalPrice').value = product.original_price || product.price;
                            document.getElementById('editProductStock').value = product.stock;
                            document.getElementById('editProductImage').value = product.image || '';
                            document.getElementById('editProductCategory').value = product.category;
                            
                            // Show modal
                            editProductModal.style.display = 'flex';
                        }
                    });
            };
            
            // Close edit modal
            document.getElementById('closeEditModal')?.addEventListener('click', function() {
                editProductModal.style.display = 'none';
            });
            
            document.getElementById('closeEditModalBtn')?.addEventListener('click', function() {
                editProductModal.style.display = 'none';
            });
            
            // Update product
            document.getElementById('updateProductBtn')?.addEventListener('click', function() {
                const productData = {
                    name: document.getElementById('editProductName').value,
                    description: document.getElementById('editProductDescription').value,
                    price: parseFloat(document.getElementById('editProductPrice').value),
                    original_price: document.getElementById('editOriginalPrice').value ? 
                        parseFloat(document.getElementById('editOriginalPrice').value) : 
                        parseFloat(document.getElementById('editProductPrice').value),
                    image: document.getElementById('editProductImage').value,
                    category: document.getElementById('editProductCategory').value,
                    stock: parseInt(document.getElementById('editProductStock').value)
                };
                
                fetch(`/api/admin/products/${currentProductId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(productData)
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        editProductModal.style.display = 'none';
                        showAlert('Product updated successfully!', 'success');
                        
                        // Reload data
                        loadProducts();
                        loadDashboard();
                    } else {
                        showAlert('Failed to update product: ' + data.message, 'error');
                    }
                })
                .catch(() => {
                    showAlert('Failed to update product. Please try again.', 'error');
                });
            });
            
            // Delete product
            window.deleteProduct = function(productId) {
                if (confirm('Are you sure you want to delete this product? This action cannot be undone.')) {
                    fetch(`/api/admin/products/${productId}`, {
                        method: 'DELETE'
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            showAlert('Product deleted successfully!', 'success');
                            
                            // Reload data
                            loadProducts();
                            loadDashboard();
                        } else {
                            showAlert('Failed to delete product: ' + data.message, 'error');
                        }
                    })
                    .catch(() => {
                        showAlert('Failed to delete product. Please try again.', 'error');
                    });
                }
            };
            
            // Export sales
            document.getElementById('exportSalesBtn')?.addEventListener('click', function() {
                window.location.href = '/api/admin/export/sales';
            });
            
            document.getElementById('exportAllSalesBtn')?.addEventListener('click', function() {
                window.location.href = '/api/admin/export/sales';
            });
            
            // Show alert
            function showAlert(message, type = 'info') {
                const alertElement = document.getElementById('alertMessage');
                const alertTitle = document.getElementById('alertTitle');
                const alertModalElement = document.getElementById('alertModal');
                
                alertMessage.textContent = message;
                
                if (type === 'success') {
                    alertTitle.textContent = 'Success';
                } else if (type === 'error') {
                    alertTitle.textContent = 'Error';
                } else {
                    alertTitle.textContent = 'Information';
                }
                
                alertModal.style.display = 'flex';
            }
            
            // Close alert modal
            document.getElementById('closeAlertModal')?.addEventListener('click', function() {
                alertModal.style.display = 'none';
            });
            
            document.getElementById('confirmAlertBtn')?.addEventListener('click', function() {
                alertModal.style.display = 'none';
            });
            
            // Initialize
            checkLogin();
        </script>
    </body>
    </html>
    """
