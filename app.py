"""
KARANJA SHOE STORE - COMPLETE FLASK APPLICATION
================================================
Full-stack inventory and sales management system with B2 cloud storage integration.
Optimized for Render deployment.

Features:
- Product management with size-specific inventory (sizes 1-50)
- Real-time sales tracking with profit calculations
- Business plan with tithe (10%), savings (20%), restock (30%)
- Daily statements and bi-weekly budget planning
- B2 cloud storage for product images
- RESTful API endpoints
"""

import os
import json
import uuid
import base64
import datetime
import hashlib
import hmac
import requests
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from b2sdk.v2 import InMemoryAccountInfo, B2Api
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
    B2_ENDPOINT = os.environ.get('B2_ENDPOINT', 'https://s3.eu-central-003.backblazeb2.com')
    
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
    DAILY_STATEMENT_TIME = 21  # 9:00 PM
    SIZE_RANGE = {'MIN': 1, 'MAX': 50}
    
    # Admin credentials (change these in production!)
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'admin@karanjashoes.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

# ==================== B2 CLOUD STORAGE MANAGER ====================
class B2StorageManager:
    """Handles all B2 cloud storage operations for product images"""
    
    def __init__(self):
        self.key_id = Config.B2_KEY_ID
        self.app_key = Config.B2_APPLICATION_KEY
        self.bucket_name = Config.B2_BUCKET_NAME
        self.bucket_id = Config.B2_BUCKET_ID
        self.endpoint = Config.B2_ENDPOINT
        self.api = None
        self.bucket = None
        self.authorized = False
        
        # Initialize B2 connection
        self._init_b2()
    
    def _init_b2(self):
        """Initialize B2 API connection"""
        try:
            info = InMemoryAccountInfo()
            self.api = B2Api(info)
            self.api.authorize_account("production", self.key_id, self.app_key)
            
            # Get or create bucket
            buckets = self.api.list_buckets()
            for bucket in buckets:
                if bucket.name == self.bucket_name:
                    self.bucket = bucket
                    break
            
            if not self.bucket:
                # Create bucket if it doesn't exist
                self.bucket = self.api.create_bucket(
                    self.bucket_name,
                    'allPrivate'
                )
            
            self.authorized = True
            print(f"✅ B2 Storage initialized: {self.bucket_name}")
            
        except Exception as e:
            print(f"❌ B2 Storage initialization failed: {e}")
            self.authorized = False
    
    def upload_image(self, image_data, filename=None, content_type='image/jpeg'):
        """
        Upload an image to B2 storage
        Returns: public URL of uploaded image
        """
        if not self.authorized:
            return self._get_placeholder_url()
        
        try:
            # Generate unique filename
            if not filename:
                ext = 'jpg'
                if 'png' in content_type.lower():
                    ext = 'png'
                elif 'gif' in content_type.lower():
                    ext = 'gif'
                filename = f"product_{uuid.uuid4().hex}.{ext}"
            else:
                filename = secure_filename(filename)
                filename = f"{uuid.uuid4().hex}_{filename}"
            
            # Upload to B2
            uploaded_file = self.bucket.upload_bytes(
                data=image_data,
                file_name=f"products/{filename}",
                content_type=content_type
            )
            
            # Generate public URL
            url = f"{self.endpoint}/{self.bucket_name}/products/{filename}"
            return url
            
        except Exception as e:
            print(f"❌ B2 upload failed: {e}")
            return self._get_placeholder_url()
    
    def delete_image(self, image_url):
        """Delete an image from B2 storage"""
        if not self.authorized or not image_url:
            return False
        
        try:
            # Extract filename from URL
            if 'products/' in image_url:
                filename = image_url.split('products/')[-1]
                file_path = f"products/{filename}"
                
                # Find and delete file
                for file_version in self.bucket.ls(file_path):
                    self.bucket.delete_file_version(
                        file_version.id_,
                        file_version.file_name
                    )
                return True
        except Exception as e:
            print(f"❌ B2 delete failed: {e}")
        
        return False
    
    def _get_placeholder_url(self):
        """Return placeholder image URL when B2 is unavailable"""
        return "https://via.placeholder.com/300x300?text=Shoe+Image"

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
        self.sizes = data.get('sizes', {})  # Dict {size: stock}
        self.buy_price = float(data.get('buy_price', 0))
        self.min_sell_price = float(data.get('min_sell_price', 0))
        self.max_sell_price = float(data.get('max_sell_price', 0))
        self.description = data.get('description', '')
        self.image = data.get('image', '')
        self.date_added = data.get('date_added', datetime.now().isoformat())
        self.last_updated = data.get('last_updated', datetime.now().isoformat())
        self.total_stock = self.calculate_total_stock()
    
    def calculate_total_stock(self):
        """Calculate total stock across all sizes"""
        total = 0
        if isinstance(self.sizes, dict):
            for size, stock in self.sizes.items():
                total += int(stock) if str(stock).isdigit() else 0
        return total
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
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
        """Convert to dictionary for JSON serialization"""
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


class Notification:
    """System notification model"""
    
    def __init__(self, message, type='info'):
        self.id = str(uuid.uuid4())
        self.message = message
        self.type = type  # success, warning, error, info
        self.timestamp = datetime.now().isoformat()
        self.read = False
    
    def to_dict(self):
        return {
            'id': self.id,
            'message': self.message,
            'type': self.type,
            'timestamp': self.timestamp,
            'read': self.read
        }


class DailyStatement:
    """Daily sales statement model"""
    
    def __init__(self, date=None):
        self.id = str(uuid.uuid4())
        self.date = date or datetime.now().isoformat()
        self.total_revenue = 0
        self.total_profit = 0
        self.total_items = 0
        self.sales_count = 0
        self.bargain_sales = 0
        self.avg_sale_value = 0
        self.category_breakdown = {}
        self.generated_at = datetime.now().isoformat()
    
    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date,
            'total_revenue': self.total_revenue,
            'total_profit': self.total_profit,
            'total_items': self.total_items,
            'sales_count': self.sales_count,
            'bargain_sales': self.bargain_sales,
            'avg_sale_value': self.avg_sale_value,
            'category_breakdown': self.category_breakdown,
            'generated_at': self.generated_at
        }


# ==================== DATABASE MANAGER ====================
class DatabaseManager:
    """
    File-based JSON storage for Render deployment
    Uses local JSON files that persist in Render's disk
    """
    
    def __init__(self):
        self.data_dir = '/var/data' if not Config.DEBUG else './data'
        self.ensure_data_directory()
        
        # File paths
        self.products_file = os.path.join(self.data_dir, 'products.json')
        self.sales_file = os.path.join(self.data_dir, 'sales.json')
        self.notifications_file = os.path.join(self.data_dir, 'notifications.json')
        self.statements_file = os.path.join(self.data_dir, 'statements.json')
        self.category_sales_file = os.path.join(self.data_dir, 'category_sales.json')
        self.settings_file = os.path.join(self.data_dir, 'settings.json')
        
        # Initialize data
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
        
        # Convert dictionaries to objects
        self._convert_to_objects()
        
        print(f"📁 Database initialized at: {self.data_dir}")
    
    def ensure_data_directory(self):
        """Create data directory if it doesn't exist"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
    
    def load_json(self, filepath, default):
        """Load JSON data from file"""
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
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
    
    def _convert_to_objects(self):
        """Convert dictionary data to objects"""
        # Products are stored as dicts, no conversion needed
        pass
    
    # ========== PRODUCT OPERATIONS ==========
    
    def get_products(self):
        """Get all products"""
        return self.products
    
    def get_product(self, product_id):
        """Get product by ID"""
        for product in self.products:
            if product.get('id') == product_id:
                return product
        return None
    
    def add_product(self, product_data):
        """Add new product"""
        product = Product(product_data).to_dict()
        self.products.append(product)
        self.save_json(self.products_file, self.products)
        return product
    
    def update_product(self, product_id, updates):
        """Update existing product"""
        for i, product in enumerate(self.products):
            if product.get('id') == product_id:
                updates['last_updated'] = datetime.now().isoformat()
                product.update(updates)
                
                # Recalculate total stock
                if 'sizes' in updates:
                    total = 0
                    for size, stock in product.get('sizes', {}).items():
                        total += int(stock) if str(stock).isdigit() else 0
                    product['total_stock'] = total
                
                self.products[i] = product
                self.save_json(self.products_file, self.products)
                return product
        return None
    
    def delete_product(self, product_id):
        """Delete product"""
        for i, product in enumerate(self.products):
            if product.get('id') == product_id:
                deleted = self.products.pop(i)
                self.save_json(self.products_file, self.products)
                return deleted
        return None
    
    # ========== SALES OPERATIONS ==========
    
    def get_sales(self):
        """Get all sales"""
        return self.sales
    
    def get_sale(self, sale_id):
        """Get sale by ID"""
        for sale in self.sales:
            if sale.get('id') == sale_id:
                return sale
        return None
    
    def add_sale(self, sale_data):
        """Add new sale transaction"""
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
                current_stock = int(product['sizes'][size])
                product['sizes'][size] = max(0, current_stock - sale['quantity'])
                self.update_product(product['id'], {'sizes': product['sizes']})
        
        # Update category sales
        self._update_category_sales(sale)
        
        return sale
    
    def _update_category_sales(self, sale):
        """Update monthly category sales statistics"""
        product = self.get_product(sale['product_id'])
        if not product:
            return
        
        category = product.get('category', 'Uncategorized')
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
    
    # ========== SALES QUERIES ==========
    
    def get_sales_by_period(self, period_days=None):
        """Get sales for a specific period"""
        if not period_days:
            return self.sales
        
        cutoff = datetime.now() - timedelta(days=period_days)
        result = []
        
        for sale in self.sales:
            try:
                sale_date = datetime.fromisoformat(sale['timestamp'])
                if sale_date >= cutoff:
                    result.append(sale)
            except:
                pass
        
        return result
    
    def get_today_sales(self):
        """Get today's sales"""
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
    
    def get_total_revenue(self, period_days=None):
        """Calculate total revenue"""
        sales = self.get_sales_by_period(period_days)
        return sum(sale.get('total_amount', 0) for sale in sales)
    
    def get_total_profit(self, period_days=None):
        """Calculate total profit"""
        sales = self.get_sales_by_period(period_days)
        return sum(sale.get('total_profit', 0) for sale in sales)
    
    def get_total_stock(self):
        """Calculate total stock across all products"""
        total = 0
        for product in self.products:
            total += product.get('total_stock', 0)
        return total
    
    # ========== NOTIFICATIONS ==========
    
    def get_notifications(self, limit=20):
        """Get recent notifications"""
        return sorted(
            self.notifications,
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )[:limit]
    
    def add_notification(self, message, type='info'):
        """Add new notification"""
        notification = Notification(message, type).to_dict()
        self.notifications.insert(0, notification)
        
        # Keep only last 100 notifications
        if len(self.notifications) > 100:
            self.notifications = self.notifications[:100]
        
        self.save_json(self.notifications_file, self.notifications)
        return notification
    
    def mark_notifications_read(self):
        """Mark all notifications as read"""
        for notification in self.notifications:
            notification['read'] = True
        self.save_json(self.notifications_file, self.notifications)
    
    def get_unread_count(self):
        """Get count of unread notifications"""
        return sum(1 for n in self.notifications if not n.get('read', True))
    
    # ========== STOCK ALERTS ==========
    
    def get_stock_alerts(self):
        """Generate stock alerts"""
        alerts = []
        
        for product in self.products:
            # Low stock alerts
            sizes = product.get('sizes', {})
            for size, stock in sizes.items():
                stock = int(stock) if str(stock).isdigit() else 0
                if 0 < stock <= Config.LOW_STOCK_THRESHOLD:
                    alerts.append({
                        'type': 'low_stock',
                        'product': product.get('name'),
                        'product_id': product.get('id'),
                        'size': size,
                        'stock': stock,
                        'message': f"{product.get('name')} (Size {size}) is running low - only {stock} left!"
                    })
            
            # Old stock alerts
            try:
                date_added = datetime.fromisoformat(product.get('date_added', ''))
                days_in_stock = (datetime.now() - date_added).days
                total_stock = product.get('total_stock', 0)
                
                if days_in_stock >= Config.OLD_STOCK_DAYS and total_stock > 0:
                    alerts.append({
                        'type': 'old_stock',
                        'product': product.get('name'),
                        'product_id': product.get('id'),
                        'days': days_in_stock,
                        'stock': total_stock,
                        'message': f"{product.get('name')} has been in stock for {days_in_stock} days - consider promotions!"
                    })
            except:
                pass
        
        return alerts
    
    # ========== BUSINESS PLANNING ==========
    
    def get_business_plan(self):
        """Calculate business plan figures"""
        total_profit = self.get_total_profit()
        total_revenue = self.get_total_revenue()
        
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
        """Calculate business health score"""
        revenue = self.get_total_revenue()
        profit = self.get_total_profit()
        
        # Calculate stock value
        stock_value = 0
        for product in self.products:
            stock_value += product.get('total_stock', 0) * product.get('buy_price', 0)
        
        # Health score components
        revenue_score = min(100, (revenue / Config.BUSINESS_HEALTH_GOAL) * 100)
        profit_margin = (profit / revenue * 100) if revenue > 0 else 0
        profit_score = min(100, profit_margin * 2)
        inventory_score = min(100, (stock_value / 50000) * 100)
        
        health_score = int((revenue_score * 0.4) + (profit_score * 0.3) + (inventory_score * 0.3))
        
        # Determine status
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
    
    def get_bi_weekly_budget(self):
        """Generate bi-weekly budget plan"""
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
        
        # Budget = 30% of profit, minimum 1000 KES
        weekly_budget = max(total_profit * 0.3, 1000)
        
        # Get category rankings
        rankings = self.get_category_rankings('current')
        high_demand = [c for c in rankings if 'High' in c.get('demand_level', '')][:3]
        low_demand = [c for c in rankings if 'Low' in c.get('demand_level', '')][:3]
        
        # Restock recommendations
        restock = []
        for product in self.products:
            if product.get('total_stock', 0) < 5:
                restock.append({
                    'product': product.get('name'),
                    'current_stock': product.get('total_stock'),
                    'recommendation': f"Restock {max(5 - product.get('total_stock', 0), 3)} units"
                })
        
        # Budget allocation
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
            'recommendation': f"Based on last 2 weeks' profit of {self.format_currency(total_profit)} ({profit_margin:.1f}% margin), allocate {self.format_currency(weekly_budget)} for inventory." if total_profit > 0 else "Not enough data for budget planning."
        }
    
    # ========== CATEGORY ANALYSIS ==========
    
    def get_category_rankings(self, period='current'):
        """Get category performance rankings"""
        now = datetime.now()
        
        if period == 'current':
            month_key = f"{now.year}-{now.month:02d}"
        elif period == 'last':
            last_month = now.replace(day=1) - timedelta(days=1)
            month_key = f"{last_month.year}-{last_month.month:02d}"
        else:
            # Aggregate last 3 months
            categories = {}
            for i in range(3):
                date = now.replace(day=1) - timedelta(days=i*30)
                key = f"{date.year}-{date.month:02d}"
                month_data = self.category_sales.get(key, {})
                
                for cat, data in month_data.items():
                    if cat not in categories:
                        categories[cat] = {'revenue': 0, 'quantity': 0, 'profit': 0}
                    categories[cat]['revenue'] += data.get('revenue', 0)
                    categories[cat]['quantity'] += data.get('quantity', 0)
                    categories[cat]['profit'] += data.get('profit', 0)
            
            # Calculate market share
            total_revenue = sum(c['revenue'] for c in categories.values())
            rankings = []
            
            for cat, data in categories.items():
                market_share = (data['revenue'] / total_revenue * 100) if total_revenue > 0 else 0
                avg_monthly = data['revenue'] / 3
                
                demand = "Medium"
                if avg_monthly > 50000:
                    demand = "Very High"
                elif avg_monthly > 20000:
                    demand = "High"
                elif avg_monthly < 5000:
                    demand = "Low"
                elif avg_monthly < 1000:
                    demand = "Very Low"
                
                rankings.append({
                    'category': cat,
                    'revenue': data['revenue'],
                    'quantity': data['quantity'],
                    'profit': data['profit'],
                    'market_share': round(market_share, 1),
                    'demand_level': demand,
                    'avg_monthly': avg_monthly
                })
            
            return sorted(rankings, key=lambda x: x['revenue'], reverse=True)
        
        # Single month
        month_data = self.category_sales.get(month_key, {})
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
    
    # ========== DAILY STATEMENT ==========
    
    def generate_daily_statement(self):
        """Generate today's sales statement"""
        today_sales = self.get_today_sales()
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # Check if already generated
        for statement in self.statements:
            try:
                if statement.get('date', '')[:10] == today_str:
                    return statement
            except:
                pass
        
        # Calculate totals
        total_revenue = sum(s.get('total_amount', 0) for s in today_sales)
        total_profit = sum(s.get('total_profit', 0) for s in today_sales)
        total_items = sum(s.get('quantity', 0) for s in today_sales)
        bargain_count = sum(1 for s in today_sales if s.get('is_bargain', False))
        
        # Category breakdown
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
        
        # Create statement
        statement = DailyStatement().to_dict()
        statement.update({
            'total_revenue': total_revenue,
            'total_profit': total_profit,
            'total_items': total_items,
            'sales_count': len(today_sales),
            'bargain_sales': bargain_count,
            'avg_sale_value': total_revenue / len(today_sales) if today_sales else 0,
            'category_breakdown': categories
        })
        
        self.statements.insert(0, statement)
        
        # Keep only last 30 statements
        if len(self.statements) > 30:
            self.statements = self.statements[:30]
        
        self.save_json(self.statements_file, self.statements)
        return statement
    
    # ========== UTILITIES ==========
    
    @staticmethod
    def format_currency(amount):
        """Format amount as currency"""
        return f"KES {float(amount):,.2f}"
    
    def get_dashboard_stats(self, period_days=None):
        """Get dashboard statistics"""
        sales = self.get_sales_by_period(period_days)
        
        return {
            'total_sales': sum(s.get('total_amount', 0) for s in sales),
            'total_profit': sum(s.get('total_profit', 0) for s in sales),
            'total_stock': self.get_total_stock(),
            'total_products': len(self.products),
            'today_sales': sum(s.get('total_amount', 0) for s in self.get_today_sales()),
            'today_profit': sum(s.get('total_profit', 0) for s in self.get_today_sales()),
            'today_items': sum(s.get('quantity', 0) for s in self.get_today_sales())
        }


# ==================== FLASK APPLICATION ====================
app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

# Enable CORS
CORS(app)

# Initialize services
db = DatabaseManager()
b2 = B2StorageManager()

# ==================== AUTHENTICATION DECORATOR ====================

def login_required(f):
    """Require authentication decorator"""
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
    return render_template('index.html')

@app.route('/api/health')
def health_check():
    """API health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'b2_storage': b2.authorized,
        'database': os.path.exists(db.data_dir)
    })

# ==================== ROUTES: AUTHENTICATION ====================

@app.route('/api/login', methods=['POST'])
def login():
    """Authenticate user"""
    data = request.json
    email = data.get('email', '')
    password = data.get('password', '')
    
    # Simple authentication for demo
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

@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout user"""
    session.clear()
    return jsonify({'success': True})

@app.route('/api/session')
def get_session():
    """Get current session info"""
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
    """Get all products"""
    return jsonify(db.get_products())

@app.route('/api/products/<product_id>', methods=['GET'])
@login_required
def get_product(product_id):
    """Get single product"""
    product = db.get_product(product_id)
    if product:
        return jsonify(product)
    return jsonify({'error': 'Product not found'}), 404

@app.route('/api/products', methods=['POST'])
@login_required
def create_product():
    """Create new product with optional image upload"""
    try:
        data = request.form.to_dict()
        image_file = request.files.get('image')
        
        # Handle image upload
        if image_file:
            image_data = image_file.read()
            content_type = image_file.content_type
            filename = image_file.filename
            
            # Upload to B2
            image_url = b2.upload_image(image_data, filename, content_type)
            data['image'] = image_url
        
        # Parse sizes JSON if provided
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        # Add product
        product = db.add_product(data)
        db.add_notification(f"New product added: {product.get('name')}", 'success')
        
        return jsonify(product), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    """Update existing product"""
    try:
        data = request.form.to_dict()
        image_file = request.files.get('image')
        
        # Handle image upload
        if image_file:
            image_data = image_file.read()
            content_type = image_file.content_type
            filename = image_file.filename
            
            # Upload to B2
            image_url = b2.upload_image(image_data, filename, content_type)
            data['image'] = image_url
        
        # Parse sizes JSON
        if 'sizes' in data and isinstance(data['sizes'], str):
            try:
                data['sizes'] = json.loads(data['sizes'])
            except:
                data['sizes'] = {}
        
        # Update product
        product = db.update_product(product_id, data)
        if product:
            return jsonify(product)
        return jsonify({'error': 'Product not found'}), 404
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    """Delete product"""
    product = db.get_product(product_id)
    if product:
        # Delete image from B2
        if product.get('image'):
            b2.delete_image(product['image'])
        
        deleted = db.delete_product(product_id)
        db.add_notification(f"Product deleted: {product.get('name')}", 'warning')
        return jsonify({'success': True, 'product': deleted})
    
    return jsonify({'error': 'Product not found'}), 404

# ==================== ROUTES: SALES ====================

@app.route('/api/sales', methods=['GET'])
@login_required
def get_sales():
    """Get all sales"""
    period = request.args.get('period')
    days = None
    
    if period == 'today':
        sales = db.get_today_sales()
    elif period == '7days':
        days = 7
        sales = db.get_sales_by_period(days)
    elif period == '1month':
        days = 30
        sales = db.get_sales_by_period(days)
    elif period == '6months':
        days = 180
        sales = db.get_sales_by_period(days)
    else:
        sales = db.get_sales()
    
    return jsonify(sales)

@app.route('/api/sales', methods=['POST'])
@login_required
def create_sale():
    """Record new sale"""
    try:
        data = request.json
        sale = db.add_sale(data)
        
        # Check stock alerts
        alerts = db.get_stock_alerts()
        for alert in alerts[:3]:
            db.add_notification(alert['message'], 'warning')
        
        return jsonify(sale), 201
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/sales/<sale_id>', methods=['GET'])
@login_required
def get_sale(sale_id):
    """Get single sale"""
    sale = db.get_sale(sale_id)
    if sale:
        return jsonify(sale)
    return jsonify({'error': 'Sale not found'}), 404

# ==================== ROUTES: STATEMENTS ====================

@app.route('/api/statements/daily', methods=['GET'])
@login_required
def get_daily_statement():
    """Get today's statement"""
    statement = db.generate_daily_statement()
    return jsonify(statement)

@app.route('/api/statements/sale/<sale_id>', methods=['GET'])
@login_required
def get_sale_statement(sale_id):
    """Get statement for specific sale"""
    sale = db.get_sale(sale_id)
    if not sale:
        return jsonify({'error': 'Sale not found'}), 404
    
    product = db.get_product(sale['product_id'])
    
    statement = {
        'id': sale.get('statement_id'),
        'sale_id': sale_id,
        'timestamp': sale.get('timestamp'),
        'product_name': sale.get('product_name'),
        'product_sku': sale.get('product_sku'),
        'product_color': product.get('color') if product else 'N/A',
        'category': product.get('category') if product else 'N/A',
        'size': sale.get('size'),
        'quantity': sale.get('quantity'),
        'unit_price': sale.get('unit_price'),
        'total_amount': sale.get('total_amount'),
        'total_profit': sale.get('total_profit'),
        'customer_name': sale.get('customer_name'),
        'is_bargain': sale.get('is_bargain'),
        'notes': sale.get('notes', 'No additional notes')
    }
    
    return jsonify(statement)

# ==================== ROUTES: DASHBOARD STATS ====================

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    """Get dashboard statistics"""
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
    """Get notifications"""
    limit = request.args.get('limit', 20, type=int)
    notifications = db.get_notifications(limit)
    return jsonify({
        'notifications': notifications,
        'unread_count': db.get_unread_count()
    })

@app.route('/api/notifications/read', methods=['POST'])
@login_required
def mark_notifications_read():
    """Mark all notifications as read"""
    db.mark_notifications_read()
    return jsonify({'success': True})

# ==================== ROUTES: STOCK ALERTS ====================

@app.route('/api/alerts/stock', methods=['GET'])
@login_required
def get_stock_alerts():
    """Get stock alerts"""
    alerts = db.get_stock_alerts()
    return jsonify(alerts)

# ==================== ROUTES: CATEGORY ANALYSIS ====================

@app.route('/api/categories/rankings', methods=['GET'])
@login_required
def get_category_rankings():
    """Get category rankings"""
    period = request.args.get('period', 'current')
    rankings = db.get_category_rankings(period)
    return jsonify(rankings)

@app.route('/api/categories/sales', methods=['GET'])
@login_required
def get_category_sales():
    """Get monthly category sales"""
    return jsonify(db.category_sales)

# ==================== ROUTES: BUSINESS PLANNING ====================

@app.route('/api/business/plan', methods=['GET'])
@login_required
def get_business_plan():
    """Get business plan calculations"""
    plan = db.get_business_plan()
    return jsonify(plan)

@app.route('/api/business/health', methods=['GET'])
@login_required
def get_business_health():
    """Get business health score"""
    health = db.get_business_health()
    return jsonify(health)

@app.route('/api/business/budget', methods=['GET'])
@login_required
def get_bi_weekly_budget():
    """Get bi-weekly budget plan"""
    budget = db.get_bi_weekly_budget()
    return jsonify(budget)

# ==================== ROUTES: CHART DATA ====================

@app.route('/api/charts/sales', methods=['GET'])
@login_required
def get_sales_chart_data():
    """Get sales chart data"""
    period = request.args.get('period', '7days')
    
    if period == '7days':
        days = 7
    elif period == '30days':
        days = 30
    elif period == '90days':
        days = 90
    else:
        days = 7
    
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
    """Get top products chart data"""
    period = request.args.get('period', '7days')
    
    if period == '7days':
        days = 7
    elif period == '30days':
        days = 30
    else:
        days = 7
    
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
    """Get category distribution chart data"""
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
    """Get business plan distribution chart"""
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
    """Export sales data as CSV"""
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
    
    # Create CSV
    output = StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['Date', 'Product', 'SKU', 'Size', 'Quantity', 
                     'Unit Price', 'Total Amount', 'Profit', 'Customer', 'Bargain'])
    
    # Data
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
    
    # Send file
    output.seek(0)
    date_str = datetime.now().strftime('%Y%m%d')
    
    return send_file(
        BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'sales_export_{date_str}.csv'
    )

# ==================== ROUTES: INITIALIZATION ====================

@app.route('/api/init/sample-data', methods=['POST'])
@login_required
def create_sample_data():
    """Create sample products and sales for testing"""
    if len(db.get_products()) > 0:
        return jsonify({'message': 'Products already exist'}), 400
    
    # Sample products
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
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff'
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
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff'
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
            'image': 'https://images.unsplash.com/photo-1542291026-7eec264c27ff'
        }
    ]
    
    for product_data in sample_products:
        db.add_product(product_data)
    
    # Sample sales
    for i, product in enumerate(db.get_products()[:3]):
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

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500

# ==================== APPLICATION ENTRY POINT ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)
