"""
KARANJA SHOE STORE - COMPLETE FLASK APPLICATION
Fixed for Render deployment - WITH PROPER TEMPLATE HANDLING
"""

import os
import json
import uuid
import base64
import datetime
import hashlib
import hmac
import requests
import traceback
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import pytz
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==================== CONFIGURATION ====================
class Config:
    # App settings
    SECRET_KEY = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    # B2 Cloud Storage Settings
    B2_KEY_ID = os.environ.get('B2_KEY_ID', '20385f075dd5')
    B2_APPLICATION_KEY = os.environ.get('B2_APPLICATION_KEY', 'Master Application Key')
    B2_BUCKET_NAME = os.environ.get('B2_BUCKET_NAME', 'karanjashoesstore')
    B2_BUCKET_ID = os.environ.get('B2_BUCKET_ID', '9240b308551f401795cd0d15')
    
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
    DAILY_STATEMENT_TIME = 21
    SIZE_RANGE = {'MIN': 1, 'MAX': 50}
    
    # Admin credentials
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@karanjashoes.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    
    # Data directory - FIXED for Render
    DATA_DIR = '/tmp/karanja-data' if not DEBUG else './data'


# ==================== B2 DIRECT API ====================
class B2DirectAPI:
    """Direct B2 API client - no b2sdk dependency"""
    
    def __init__(self, key_id, application_key, bucket_name, bucket_id):
        self.key_id = key_id
        self.application_key = application_key
        self.bucket_name = bucket_name
        self.bucket_id = bucket_id
        self.api_url = None
        self.download_url = None
        self.authorization_token = None
        self.authorized = False
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with B2 API"""
        try:
            auth_string = f"{self.key_id}:{self.application_key}"
            auth_header = base64.b64encode(auth_string.encode()).decode()
            
            response = requests.get(
                "https://api.backblazeb2.com/b2api/v2/b2_authorize_account",
                headers={"Authorization": f"Basic {auth_header}"},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.api_url = data['apiUrl']
                self.download_url = data['downloadUrl']
                self.authorization_token = data['authorizationToken']
                self.authorized = True
                print(f"✅ B2 Authenticated: {self.bucket_name}")
            else:
                print(f"❌ B2 Auth failed: {response.status_code}")
                self.authorized = False
        except Exception as e:
            print(f"❌ B2 Auth error: {e}")
            self.authorized = False
    
    def get_upload_url(self):
        """Get upload URL and token"""
        if not self.authorized:
            return None, None
        
        try:
            response = requests.post(
                f"{self.api_url}/b2api/v2/b2_get_upload_url",
                headers={"Authorization": self.authorization_token},
                json={"bucketId": self.bucket_id},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                return data['uploadUrl'], data['authorizationToken']
        except Exception as e:
            print(f"❌ B2 get_upload_url error: {e}")
        
        return None, None
    
    def upload_file(self, file_data, file_name, content_type='image/jpeg'):
        """Upload file directly to B2"""
        if not self.authorized:
            return self._get_placeholder_url()
        
        try:
            upload_url, upload_token = self.get_upload_url()
            if not upload_url:
                return self._get_placeholder_url()
            
            # Generate unique filename
            ext = file_name.split('.')[-1] if '.' in file_name else 'jpg'
            unique_name = f"products/{uuid.uuid4().hex}.{ext}"
            
            headers = {
                "Authorization": upload_token,
                "X-Bz-File-Name": unique_name,
                "Content-Type": content_type,
                "X-Bz-Content-Sha1": hashlib.sha1(file_data).hexdigest()
            }
            
            response = requests.post(upload_url, headers=headers, data=file_data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                return f"https://{self.bucket_name}.s3.{self._get_region()}.backblazeb2.com/{unique_name}"
            
        except Exception as e:
            print(f"❌ B2 upload failed: {e}")
        
        return self._get_placeholder_url()
    
    def _get_region(self):
        """Extract region from API URL"""
        if 'eu-central' in str(self.api_url):
            return 'eu-central-003'
        return 'us-west-002'
    
    def _get_placeholder_url(self):
        return "https://via.placeholder.com/300x300?text=Shoe+Image"


# ==================== B2 STORAGE MANAGER ====================
class B2StorageManager:
    """Handles B2 cloud storage operations"""
    
    def __init__(self):
        self.key_id = Config.B2_KEY_ID
        self.app_key = Config.B2_APPLICATION_KEY
        self.bucket_name = Config.B2_BUCKET_NAME
        self.bucket_id = Config.B2_BUCKET_ID
        self.api = B2DirectAPI(
            self.key_id, 
            self.app_key, 
            self.bucket_name, 
            self.bucket_id
        )
        self.authorized = self.api.authorized
    
    def upload_image(self, image_data, filename=None, content_type='image/jpeg'):
        """Upload an image to B2 storage"""
        if not filename:
            filename = f"image_{uuid.uuid4().hex}.jpg"
        
        return self.api.upload_file(image_data, filename, content_type)
    
    def delete_image(self, image_url):
        """Delete image from B2 storage"""
        return True


# ==================== DATA MODELS ====================
class Product:
    """Product model with size-specific inventory"""
    
    def __init__(self, data=None):
        if data is None:
            data = {}
        
        self.id = data.get('id', str(uuid.uuid4()))
        self.name = data.get('name', '')
        self.sku = data.get('sku', '')
        self.category = data.get('category', '')
        self.color = data.get('color', '')
        self.sizes = data.get('sizes', {})
        self.buy_price = float(data.get('buy_price', 0))
        self.min_sell_price = float(data.get('min_sell_price', 0))
        self.max_sell_price = float(data.get('max_sell_price', 0))
        self.description = data.get('description', '')
        self.image = data.get('image', '')
        self.date_added = data.get('date_added', datetime.now().isoformat())
        self.last_updated = data.get('last_updated', datetime.now().isoformat())
        self.total_stock = self.calculate_total_stock()
    
    def calculate_total_stock(self):
        total = 0
        if isinstance(self.sizes, dict):
            for size, stock in self.sizes.items():
                try:
                    total += int(stock) if str(stock).isdigit() else 0
                except:
                    pass
        return total
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'sku': self.sku,
            'category': self.category,
            'color': self.color,
            'sizes': self.sizes,
            'buy_price': self.buy_price,
            'min_sell_price': self.min_sell_price,
            'max_sell_price': self.max_sell_price,
            'description': self.description,
            'image': self.image,
            'date_added': self.date_added,
            'last_updated': self.last_updated,
            'total_stock': self.calculate_total_stock()
        }


class Sale:
    """Sale transaction model"""
    
    def __init__(self, data=None):
        if data is None:
            data = {}
        
        self.id = data.get('id', str(uuid.uuid4()))
        self.product_id = data.get('product_id', '')
        self.product_name = data.get('product_name', '')
        self.product_sku = data.get('product_sku', '')
        self.size = data.get('size', '')
        self.quantity = int(data.get('quantity', 1))
        self.unit_price = float(data.get('unit_price', 0))
        self.unit_cost = float(data.get('unit_cost', 0))
        self.total_amount = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost
        self.total_profit = self.total_amount - self.total_cost
        self.customer_name = data.get('customer_name', 'Walk-in Customer')
        self.notes = data.get('notes', '')
        self.is_bargain = data.get('is_bargain', False)
        self.timestamp = data.get('timestamp', datetime.now().isoformat())
        self.statement_id = data.get('statement_id', f"STMT-{uuid.uuid4().hex[:8].upper()}")
    
    def to_dict(self):
        return {
            'id': self.id,
            'product_id': self.product_id,
            'product_name': self.product_name,
            'product_sku': self.product_sku,
            'size': self.size,
            'quantity': self.quantity,
            'unit_price': self.unit_price,
            'unit_cost': self.unit_cost,
            'total_amount': self.total_amount,
            'total_cost': self.total_cost,
            'total_profit': self.total_profit,
            'customer_name': self.customer_name,
            'notes': self.notes,
            'is_bargain': self.is_bargain,
            'timestamp': self.timestamp,
            'statement_id': self.statement_id
        }


# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    """File-based JSON storage - Works on Render with /tmp directory"""
    
    def __init__(self):
        # Use Config.DATA_DIR which is set to /tmp/karanja-data on Render
        self.data_dir = Config.DATA_DIR
        self.ensure_data_directory()
        
        self.products_file = os.path.join(self.data_dir, 'products.json')
        self.sales_file = os.path.join(self.data_dir, 'sales.json')
        self.notifications_file = os.path.join(self.data_dir, 'notifications.json')
        self.statements_file = os.path.join(self.data_dir, 'statements.json')
        self.category_sales_file = os.path.join(self.data_dir, 'category_sales.json')
        self.settings_file = os.path.join(self.data_dir, 'settings.json')
        
        # Initialize data with empty defaults
        self.products = self.load_json(self.products_file, [])
        self.sales = self.load_json(self.sales_file, [])
        self.notifications = self.load_json(self.notifications_file, [])
        self.statements = self.load_json(self.statements_file, [])
        self.category_sales = self.load_json(self.category_sales_file, {})
        self.settings = self.load_json(self.settings_file, {
            'currency': 'KES',
            'low_stock_threshold': 3,
            'old_stock_days': 30,
            'monthly_goals': {}
        })
        
        print(f"📁 Database initialized at: {self.data_dir}")
        print(f"📊 Products: {len(self.products)} | Sales: {len(self.sales)}")
    
    def ensure_data_directory(self):
        """Create data directory if it doesn't exist"""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            print(f"✅ Data directory ready: {self.data_dir}")
        except Exception as e:
            print(f"⚠️ Could not create {self.data_dir}, using current directory")
            # Fallback to current directory
            self.data_dir = './data'
            os.makedirs(self.data_dir, exist_ok=True)
    
    def load_json(self, filepath, default):
        """Load JSON data from file"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"✅ Loaded {os.path.basename(filepath)}")
                    return data
        except Exception as e:
            print(f"⚠️ Error loading {filepath}: {e}")
        return default
    
    def save_json(self, filepath, data):
        """Save JSON data to file"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"❌ Error saving {filepath}: {e}")
            return False
    
    # ========== PRODUCT OPERATIONS ==========
    
    def get_products(self):
        return self.products
    
    def get_product(self, product_id):
        for product in self.products:
            if product.get('id') == product_id:
                return product
        return None
    
    def add_product(self, product_data):
        product = Product(product_data).to_dict()
        self.products.append(product)
        self.save_json(self.products_file, self.products)
        return product
    
    def update_product(self, product_id, updates):
        for i, product in enumerate(self.products):
            if product.get('id') == product_id:
                updates['last_updated'] = datetime.now().isoformat()
                product.update(updates)
                
                if 'sizes' in updates:
                    total = 0
                    for size, stock in product.get('sizes', {}).items():
                        try:
                            total += int(stock) if str(stock).isdigit() else 0
                        except:
                            pass
                    product['total_stock'] = total
                
                self.products[i] = product
                self.save_json(self.products_file, self.products)
                return product
        return None
    
    def delete_product(self, product_id):
        for i, product in enumerate(self.products):
            if product.get('id') == product_id:
                deleted = self.products.pop(i)
                self.save_json(self.products_file, self.products)
                return deleted
        return None
    
    # ========== SALES OPERATIONS ==========
    
    def get_sales(self):
        return self.sales
    
    def get_sale(self, sale_id):
        for sale in self.sales:
            if sale.get('id') == sale_id:
                return sale
        return None
    
    def add_sale(self, sale_data):
        sale = Sale(sale_data).to_dict()
        self.sales.insert(0, sale)
        
        # Keep only last 1000 sales
        if len(self.sales) > 1000:
            self.sales = self.sales[:1000]
        
        self.save_json(self.sales_file, self.sales)
        
        # Update product stock
        product = self.get_product(sale['product_id'])
        if product and 'sizes' in product:
            size = str(sale['size'])
            if size in product['sizes']:
                try:
                    current_stock = int(product['sizes'][size])
                    product['sizes'][size] = max(0, current_stock - sale['quantity'])
                    self.update_product(product['id'], {'sizes': product['sizes']})
                except:
                    pass
        
        self._update_category_sales(sale)
        
        return sale
    
    def _update_category_sales(self, sale):
        product = self.get_product(sale['product_id'])
        if not product:
            return
        
        category = product.get('category', 'Uncategorized')
        try:
            date = datetime.fromisoformat(sale['timestamp'])
            month_key = f"{date.year}-{date.month:02d}"
            
            if month_key not in self.category_sales:
                self.category_sales[month_key] = {}
            
            if category not in self.category_sales[month_key]:
                self.category_sales[month_key][category] = {
                    'revenue': 0,
                    'quantity': 0,
                    'profit': 0
                }
            
            self.category_sales[month_key][category]['revenue'] += sale['total_amount']
            self.category_sales[month_key][category]['quantity'] += sale['quantity']
            self.category_sales[month_key][category]['profit'] += sale['total_profit']
            
            self.save_json(self.category_sales_file, self.category_sales)
        except Exception as e:
            print(f"⚠️ Error updating category sales: {e}")
    
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
    
    # ========== NOTIFICATIONS ==========
    
    def get_notifications(self, limit=20):
        return sorted(
            self.notifications,
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )[:limit]
    
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
    
    def mark_notifications_read(self):
        for notification in self.notifications:
            notification['read'] = True
        self.save_json(self.notifications_file, self.notifications)
    
    def get_unread_count(self):
        return sum(1 for n in self.notifications if not n.get('read', True))
    
    # ========== DASHBOARD STATS ==========
    
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
    
    # ========== BUSINESS PLAN ==========
    
    def get_business_plan(self):
        total_profit = sum(s.get('total_profit', 0) for s in self.sales)
        total_revenue = sum(s.get('total_amount', 0) for s in self.sales)
        
        return {
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'tithe': total_profit * (Config.TITHE_PERCENTAGE / 100),
            'savings': total_profit * (Config.SAVINGS_PERCENTAGE / 100),
            'restock': total_profit * (Config.RESTOCK_PERCENTAGE / 100),
            'deductions': total_profit * (Config.DEDUCTIONS_PERCENTAGE / 100),
            'personal_income': total_profit * (Config.PERSONAL_INCOME_PERCENTAGE / 100),
            'profit_margin': (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        }
    
    def get_business_health(self):
        revenue = sum(s.get('total_amount', 0) for s in self.sales)
        profit = sum(s.get('total_profit', 0) for s in self.sales)
        
        stock_value = sum(p.get('total_stock', 0) * p.get('buy_price', 0) for p in self.products)
        
        revenue_score = min(100, (revenue / Config.BUSINESS_HEALTH_GOAL) * 100)
        profit_margin = (profit / revenue * 100) if revenue > 0 else 0
        profit_score = min(100, profit_margin * 2)
        inventory_score = min(100, (stock_value / 50000) * 100)
        
        health_score = int((revenue_score * 0.4) + (profit_score * 0.3) + (inventory_score * 0.3))
        
        if health_score >= 85:
            status = "Excellent"
        elif health_score >= 70:
            status = "Very Good"
        elif health_score >= 50:
            status = "Good"
        elif health_score >= 30:
            status = "Fair"
        else:
            status = "Needs Improvement"
        
        return {
            'score': health_score,
            'status': status,
            'breakdown': {
                'revenue': revenue_score,
                'profit': profit_score,
                'inventory': inventory_score
            }
        }
    
    # ========== CATEGORY RANKINGS ==========
    
    def get_category_rankings(self, period='current'):
        now = datetime.now()
        
        if period == 'current':
            month_key = f"{now.year}-{now.month:02d}"
            month_data = self.category_sales.get(month_key, {})
        elif period == 'last':
            last_month = now.replace(day=1) - timedelta(days=1)
            month_key = f"{last_month.year}-{last_month.month:02d}"
            month_data = self.category_sales.get(month_key, {})
        else:
            # Aggregate last 3 months
            categories = {}
            for i in range(3):
                date = now.replace(day=1) - timedelta(days=i*30)
                key = f"{date.year}-{date.month:02d}"
                data = self.category_sales.get(key, {})
                for cat, values in data.items():
                    if cat not in categories:
                        categories[cat] = {'revenue': 0, 'quantity': 0, 'profit': 0}
                    categories[cat]['revenue'] += values.get('revenue', 0)
                    categories[cat]['quantity'] += values.get('quantity', 0)
                    categories[cat]['profit'] += values.get('profit', 0)
            month_data = categories
        
        total_revenue = sum(c.get('revenue', 0) for c in month_data.values())
        rankings = []
        
        for cat, data in month_data.items():
            market_share = (data['revenue'] / total_revenue * 100) if total_revenue > 0 else 0
            
            demand = "Medium"
            if data['revenue'] > 50000:
                demand = "Very High"
            elif data['revenue'] > 20000:
                demand = "High"
            elif data['revenue'] < 5000:
                demand = "Low"
            elif data['revenue'] < 1000:
                demand = "Very Low"
            
            rankings.append({
                'category': cat,
                'revenue': data['revenue'],
                'quantity': data['quantity'],
                'profit': data['profit'],
                'market_share': round(market_share, 1),
                'demand_level': demand
            })
        
        return sorted(rankings, key=lambda x: x['revenue'], reverse=True)
    
    # ========== STOCK ALERTS ==========
    
    def get_stock_alerts(self):
        alerts = []
        
        for product in self.products:
            sizes = product.get('sizes', {})
            for size, stock in sizes.items():
                try:
                    stock = int(stock) if str(stock).isdigit() else 0
                    if 0 < stock <= Config.LOW_STOCK_THRESHOLD:
                        alerts.append({
                            'type': 'low_stock',
                            'product': product.get('name'),
                            'product_id': product.get('id'),
                            'size': size,
                            'stock': stock,
                            'message': f"{product.get('name')} (Size {size}) - only {stock} left!"
                        })
                except:
                    pass
        
        return alerts
    
    # ========== DAILY STATEMENT ==========
    
    def generate_daily_statement(self):
        today_sales = self.get_today_sales()
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # Check if already generated
        for statement in self.statements:
            try:
                if statement.get('date', '')[:10] == today_str:
                    return statement
            except:
                pass
        
        total_revenue = sum(s.get('total_amount', 0) for s in today_sales)
        total_profit = sum(s.get('total_profit', 0) for s in today_sales)
        total_items = sum(s.get('quantity', 0) for s in today_sales)
        bargain_count = sum(1 for s in today_sales if s.get('is_bargain', False))
        
        categories = {}
        for sale in today_sales:
            product = self.get_product(sale['product_id'])
            if product:
                cat = product.get('category', 'Uncategorized')
                if cat not in categories:
                    categories[cat] = {'revenue': 0, 'items': 0, 'profit': 0}
                categories[cat]['revenue'] += sale['total_amount']
                categories[cat]['items'] += sale['quantity']
                categories[cat]['profit'] += sale['total_profit']
        
        statement = {
            'id': str(uuid.uuid4()),
            'date': datetime.now().isoformat(),
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'total_items': total_items,
            'sales_count': len(today_sales),
            'bargain_sales': bargain_count,
            'avg_sale_value': total_revenue / len(today_sales) if today_sales else 0,
            'category_breakdown': categories,
            'generated_at': datetime.now().isoformat()
        }
        
        self.statements.insert(0, statement)
        
        if len(self.statements) > 30:
            self.statements = self.statements[:30]
        
        self.save_json(self.statements_file, self.statements)
        return statement
    
    # ========== BI-WEEKLY BUDGET ==========
    
    def get_bi_weekly_budget(self):
        two_weeks_ago = datetime.now() - timedelta(days=14)
        recent_sales = []
        
        for sale in self.sales:
            try:
                sale_date = datetime.fromisoformat(sale['timestamp'])
                if sale_date >= two_weeks_ago:
                    recent_sales.append(sale)
            except:
                pass
        
        total_revenue = sum(s.get('total_amount', 0) for s in recent_sales)
        total_profit = sum(s.get('total_profit', 0) for s in recent_sales)
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        weekly_budget = max(total_profit * 0.3, 1000)
        
        rankings = self.get_category_rankings('current')
        high_demand = [c for c in rankings if 'High' in c.get('demand_level', '')][:3]
        low_demand = [c for c in rankings if 'Low' in c.get('demand_level', '')][:3]
        
        restock = []
        for product in self.products:
            if product.get('total_stock', 0) < 5:
                restock.append({
                    'product': product.get('name'),
                    'current_stock': product.get('total_stock'),
                    'recommendation': f"Restock {max(5 - product.get('total_stock', 0), 3)} units"
                })
        
        allocation = [
            {'category': 'High Demand Products', 'percentage': 50, 'amount': weekly_budget * 0.5},
            {'category': 'Restock Fast Movers', 'percentage': 30, 'amount': weekly_budget * 0.3},
            {'category': 'New Opportunities', 'percentage': 15, 'amount': weekly_budget * 0.15},
            {'category': 'Emergency Buffer', 'percentage': 5, 'amount': weekly_budget * 0.05}
        ]
        
        return {
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'profit_margin': round(profit_margin, 1),
            'weekly_budget': weekly_budget,
            'high_demand': high_demand[:3],
            'low_demand': low_demand[:3],
            'restock_recommendations': restock[:5],
            'budget_allocation': allocation,
            'recommendation': f"Based on last 2 weeks' profit of KES {total_profit:,.2f} ({profit_margin:.1f}% margin), allocate KES {weekly_budget:,.2f} for inventory." if total_profit > 0 else "Not enough data for budget planning."
        }
    
    @staticmethod
    def format_currency(amount):
        return f"KES {float(amount):,.2f}"


# ==================== FLASK APPLICATION ====================
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

CORS(app)

# Initialize services
db = DatabaseManager()
b2 = B2StorageManager()


# ==================== ERROR HANDLER FOR DEBUGGING ====================
@app.errorhandler(Exception)
def handle_exception(e):
    """Global exception handler"""
    print(f"❌ Unhandled exception: {str(e)}")
    print(traceback.format_exc())
    return jsonify({
        'error': 'Internal server error',
        'message': str(e) if Config.DEBUG else 'An unexpected error occurred'
    }), 500


# ==================== AUTHENTICATION DECORATOR ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function


# ==================== ROUTES: MAIN ====================
@app.route('/')
def index():
    """Serve the main application"""
    try:
        # Check if template exists
        template_path = os.path.join(app.root_path, 'templates', 'index.html')
        if not os.path.exists(template_path):
            print(f"⚠️ Template not found at: {template_path}")
            return "Karanja Shoe Store - Template not found. Please check deployment.", 500
        
        return render_template('index.html')
    except Exception as e:
        print(f"❌ Error rendering template: {e}")
        print(traceback.format_exc())
        return f"Error loading application: {str(e)}", 500

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    template_exists = os.path.exists(os.path.join(app.root_path, 'templates', 'index.html'))
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'b2_storage': b2.authorized,
        'database': {
            'path': db.data_dir,
            'exists': os.path.exists(db.data_dir),
            'writable': os.access(db.data_dir, os.W_OK) if os.path.exists(db.data_dir) else False
        },
        'template': {
            'exists': template_exists,
            'path': os.path.join(app.root_path, 'templates', 'index.html')
        },
        'products': len(db.products),
        'sales': len(db.sales)
    })


# ==================== ROUTES: AUTHENTICATION ====================
@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        email = data.get('email', '')
        password = data.get('password', '')
        
        if email == Config.ADMIN_EMAIL and password == Config.ADMIN_PASSWORD:
            session['logged_in'] = True
            session['user'] = {'email': email, 'name': 'Admin Karanja'}
            return jsonify({
                'success': True,
                'user': {
                    'email': email,
                    'name': 'Admin Karanja',
                    'role': 'admin'
                }
            })
        
        return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
    except Exception as e:
        print(f"❌ Login error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/session')
def get_session():
    if session.get('logged_in'):
        return jsonify({
            'logged_in': True,
            'user': session.get('user')
        })
    return jsonify({'logged_in': False})


# ==================== ROUTES: PRODUCTS ====================
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    return jsonify(db.get_products())

@app.route('/api/products/<product_id>', methods=['GET'])
@login_required
def get_product(product_id):
    product = db.get_product(product_id)
    if product:
        return jsonify(product)
    return jsonify({'error': 'Product not found'}), 404

@app.route('/api/products', methods=['POST'])
@login_required
def create_product():
    try:
        data = request.form.to_dict()
        image_file = request.files.get('image')
        
        if image_file:
            image_data = image_file.read()
            content_type = image_file.content_type
            filename = image_file.filename
            
            image_url = b2.upload_image(image_data, filename, content_type)
            data['image'] = image_url
        
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        product = db.add_product(data)
        db.add_notification(f"New product added: {product.get('name')}", 'success')
        
        return jsonify(product), 201
        
    except Exception as e:
        print(f"❌ Error creating product: {e}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    try:
        data = request.form.to_dict()
        image_file = request.files.get('image')
        
        if image_file:
            image_data = image_file.read()
            content_type = image_file.content_type
            filename = image_file.filename
            
            image_url = b2.upload_image(image_data, filename, content_type)
            data['image'] = image_url
        
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        product = db.update_product(product_id, data)
        if product:
            return jsonify(product)
        return jsonify({'error': 'Product not found'}), 404
        
    except Exception as e:
        print(f"❌ Error updating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    product = db.get_product(product_id)
    if product:
        deleted = db.delete_product(product_id)
        db.add_notification(f"Product deleted: {product.get('name')}", 'warning')
        return jsonify({'success': True, 'product': deleted})
    
    return jsonify({'error': 'Product not found'}), 404


# ==================== ROUTES: SALES ====================
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
        
        alerts = db.get_stock_alerts()
        for alert in alerts[:3]:
            db.add_notification(alert['message'], 'warning')
        
        return jsonify(sale), 201
        
    except Exception as e:
        print(f"❌ Error creating sale: {e}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


# ==================== ROUTES: STATS ====================
@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    period = request.args.get('period', 'today')
    
    days = None
    if period == 'today':
        days = 1
    elif period == '7days':
        days = 7
    elif period == '1month':
        days = 30
    elif period == '6months':
        days = 180
    elif period == '12months':
        days = 365
    
    stats = db.get_dashboard_stats(days)
    stats['period'] = period
    
    return jsonify(stats)


# ==================== ROUTES: NOTIFICATIONS ====================
@app.route('/api/notifications', methods=['GET'])
@login_required
def get_notifications():
    limit = request.args.get('limit', 20, type=int)
    notifications = db.get_notifications(limit)
    return jsonify({
        'notifications': notifications,
        'unread_count': db.get_unread_count()
    })

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    db.mark_notifications_read()
    return jsonify({'success': True})


# ==================== ROUTES: ALERTS ====================
@app.route('/api/alerts/stock', methods=['GET'])
@login_required
def get_stock_alerts():
    alerts = db.get_stock_alerts()
    return jsonify(alerts)


# ==================== ROUTES: CATEGORIES ====================
@app.route('/api/categories/rankings', methods=['GET'])
@login_required
def get_category_rankings():
    period = request.args.get('period', 'current')
    rankings = db.get_category_rankings(period)
    return jsonify(rankings)


# ==================== ROUTES: BUSINESS ====================
@app.route('/api/business/plan', methods=['GET'])
@login_required
def get_business_plan():
    plan = db.get_business_plan()
    return jsonify(plan)

@app.route('/api/business/health', methods=['GET'])
@login_required
def get_business_health():
    health = db.get_business_health()
    return jsonify(health)

@app.route('/api/business/budget', methods=['GET'])
@login_required
def get_bi_weekly_budget():
    budget = db.get_bi_weekly_budget()
    return jsonify(budget)


# ==================== ROUTES: STATEMENTS ====================
@app.route('/api/statements/daily', methods=['GET'])
@login_required
def get_daily_statement():
    statement = db.generate_daily_statement()
    return jsonify(statement)


# ==================== ROUTES: CHARTS ====================
@app.route('/api/charts/sales', methods=['GET'])
@login_required
def get_sales_chart():
    days = int(request.args.get('days', 7))
    sales = db.get_sales_by_period(days)
    today = datetime.now()
    
    labels = []
    data = []
    
    for i in range(days - 1, -1, -1):
        date = today - timedelta(days=i)
        labels.append(date.strftime('%b %d'))
        
        daily_total = 0
        for sale in sales:
            try:
                sale_date = datetime.fromisoformat(sale['timestamp'])
                if sale_date.date() == date.date():
                    daily_total += sale.get('total_amount', 0)
            except:
                pass
        
        data.append(daily_total)
    
    return jsonify({
        'labels': labels,
        'datasets': [{
            'label': 'Sales (KES)',
            'data': data,
            'borderColor': '#2196f3',
            'backgroundColor': 'rgba(33, 150, 243, 0.1)'
        }]
    })

@app.route('/api/charts/top-products', methods=['GET'])
@login_required
def get_top_products_chart():
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

@app.route('/api/charts/category', methods=['GET'])
@login_required
def get_category_chart():
    period = request.args.get('period', 'current')
    rankings = db.get_category_rankings(period)
    
    return jsonify({
        'labels': [r['category'] for r in rankings[:7]],
        'datasets': [{
            'data': [r['revenue'] for r in rankings[:7]],
            'backgroundColor': [
                '#ff5722', '#2196f3', '#4caf50', '#ff9800',
                '#9c27b0', '#009688', '#795548'
            ]
        }]
    })

@app.route('/api/charts/business-plan', methods=['GET'])
@login_required
def get_business_plan_chart():
    plan = db.get_business_plan()
    total_profit = plan['total_profit']
    
    if total_profit > 0:
        return jsonify({
            'labels': ['Tithe (10%)', 'Savings (20%)', 'Restock (30%)', 'Deductions (15%)', 'Personal (25%)'],
            'datasets': [{
                'data': [
                    plan['tithe'],
                    plan['savings'],
                    plan['restock'],
                    plan['deductions'],
                    plan['personal_income']
                ],
                'backgroundColor': ['#9c27b0', '#4caf50', '#2196f3', '#ff9800', '#ff5722']
            }]
        })
    
    return jsonify({
        'labels': [],
        'datasets': [{'data': []}]
    })


# ==================== ROUTES: EXPORT ====================
@app.route('/api/export/sales', methods=['GET'])
@login_required
def export_sales():
    import csv
    from io import StringIO
    
    period = request.args.get('period', 'all')
    
    if period == 'today':
        sales = db.get_today_sales()
    elif period == '7days':
        sales = db.get_sales_by_period(7)
    elif period == '30days':
        sales = db.get_sales_by_period(30)
    else:
        sales = db.get_sales()
    
    output = StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Date', 'Product', 'SKU', 'Size', 'Quantity', 
                     'Unit Price', 'Total Amount', 'Profit', 'Customer', 'Bargain'])
    
    for sale in sales:
        writer.writerow([
            sale.get('timestamp', ''),
            sale.get('product_name', ''),
            sale.get('product_sku', ''),
            sale.get('size', ''),
            sale.get('quantity', 0),
            sale.get('unit_price', 0),
            sale.get('total_amount', 0),
            sale.get('total_profit', 0),
            sale.get('customer_name', ''),
            'Yes' if sale.get('is_bargain') else 'No'
        ])
    
    output.seek(0)
    date_str = datetime.now().strftime('%Y%m%d')
    
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'sales_export_{date_str}.csv'
    )


# ==================== ROUTES: INIT SAMPLE DATA ====================
@app.route('/api/init/sample-data', methods=['POST'])
@login_required
def create_sample_data():
    if len(db.get_products()) > 0:
        return jsonify({'message': 'Products already exist'}), 400
    
    sample_products = [
        {
            'name': 'Nike Air Max',
            'sku': 'KS-001',
            'category': 'Sports Shoes',
            'color': 'Black/White',
            'sizes': {'42': 10, '43': 8, '44': 5},
            'buy_price': 3500,
            'min_sell_price': 4500,
            'max_sell_price': 5500,
            'description': 'Comfortable running shoes',
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
            'description': 'Classic tennis shoes',
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=300'
        },
        {
            'name': 'Timberland Boots',
            'sku': 'KS-003',
            'category': 'Boots',
            'color': 'Brown',
            'sizes': {'43': 6, '44': 4, '45': 3},
            'buy_price': 4500,
            'min_sell_price': 6000,
            'max_sell_price': 7500,
            'description': 'Durable work boots',
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=300'
        }
    ]
    
    for product_data in sample_products:
        db.add_product(product_data)
    
    for product in db.get_products()[:3]:
        sizes = list(product.get('sizes', {}).keys())
        if sizes:
            sale_data = {
                'product_id': product['id'],
                'product_name': product['name'],
                'product_sku': product['sku'],
                'size': sizes[0],
                'quantity': 2,
                'unit_price': product['max_sell_price'],
                'unit_cost': product['buy_price'],
                'customer_name': 'Sample Customer',
                'notes': 'Sample sale',
                'is_bargain': False
            }
            db.add_sale(sale_data)
    
    db.add_notification('Sample data created successfully!', 'success')
    
    return jsonify({
        'success': True,
        'message': 'Sample data created',
        'products_count': len(db.get_products()),
        'sales_count': len(db.get_sales())
    })


# ==================== APPLICATION ENTRY POINT ====================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    # Print startup information
    print("=" * 50)
    print("🚀 KARANJA SHOE STORE STARTING...")
    print(f"📁 Data directory: {Config.DATA_DIR}")
    print(f"📁 Template path: {os.path.join(app.root_path, 'templates', 'index.html')}")
    print(f"🔑 B2 Storage: {'✅ Connected' if b2.authorized else '❌ Not connected'}")
    print(f"🌐 Port: {port}")
    print(f"🐍 Debug mode: {Config.DEBUG}")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)
