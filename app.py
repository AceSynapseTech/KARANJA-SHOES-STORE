from flask import Flask, request, jsonify, send_file, send_from_directory, make_response, url_for
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
import json
import os
from supabase import create_client, Client
from werkzeug.utils import secure_filename
import uuid
import logging
import traceback
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import qrcode
from io import BytesIO
import base64
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
import pdfkit
import datetime as dt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== CONFIGURATION ====================
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'karanja-shoe-store-secret-key-2026')
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'karanja-jwt-secret-key-2026')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB

# Create necessary directories
os.makedirs('static', exist_ok=True)
os.makedirs('receipts', exist_ok=True)
os.makedirs('statements', exist_ok=True)
os.makedirs('reports', exist_ok=True)

# ==================== CONSTANT LOGIN CREDENTIALS ====================
CONSTANT_EMAIL = "KARANJASHOESTORE@GMAIL.COM"
CONSTANT_PASSWORD = "0726539216"
CONSTANT_USER_ID = "1"
CONSTANT_USER_NAME = "Karanja Shoe Store"
CONSTANT_USER_ROLE = "admin"

# ==================== EMAIL CONFIGURATION ====================
EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'sender_email': 'karanjashoestore@gmail.com',  # Update with your Gmail
    'sender_password': 'your-app-password-here',  # Use App Password, not regular password
    'backup_emails': ['fm4461014@gmail.com', 'bonnykaranja001@gmail.com']
}

# ==================== WHATSAPP CONFIGURATION ====================
WHATSAPP_CONFIG = {
    'api_url': 'https://graph.facebook.com/v17.0/YOUR_PHONE_NUMBER_ID/messages',
    'access_token': 'your-whatsapp-access-token',
    'recipients': ['254726539216', '254756194207']  # Without + sign
}

# ==================== SUPABASE CONFIGURATION ====================
SUPABASE_URL = "https://hgcknskdvbgfiubfxdeo.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhnY2tuc2tkdmJnZml1YmZ4ZGVvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE2MDE3MTQsImV4cCI6MjA4NzE3NzcxNH0.xuRf8pqb8DJmPtawGC8zmBQQrSo3ukEVSqe6KPyEofg"

# Buckets/Storage configuration
STORAGE_BUCKET = "product-images"

# Initialize Supabase client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✓ Supabase client initialized successfully")
    
    # Test connection
    try:
        test_query = supabase.table('products').select('*').limit(1).execute()
        logger.info("✓ Database connection successful")
        SUPABASE_AVAILABLE = True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        SUPABASE_AVAILABLE = False
        
except Exception as e:
    logger.error(f"✗ Failed to initialize Supabase client: {e}")
    SUPABASE_AVAILABLE = False
    supabase = None

# ==================== EXTENSIONS ====================
CORS(app)
jwt = JWTManager(app)

# ==================== HELPER FUNCTIONS ====================

def get_table_data(table_name):
    """Get all data from a Supabase table"""
    if not supabase:
        logger.error(f"Supabase not available for {table_name}")
        return []
    try:
        response = supabase.table(table_name).select("*").execute()
        logger.info(f"Retrieved {len(response.data)} records from {table_name}")
        return response.data
    except Exception as e:
        logger.error(f"Error reading from {table_name}: {e}")
        return []

def save_table_data(table_name, data):
    """Save data to Supabase table"""
    if not supabase:
        logger.error(f"Supabase not available for saving to {table_name}")
        return False
    try:
        if isinstance(data, list):
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"✓ Saved {len(data)} records to {table_name}")
        else:
            result = supabase.table(table_name).upsert(data).execute()
            logger.info(f"✓ Saved single record to {table_name} with ID: {data.get('id', 'unknown')}")
        return True
    except Exception as e:
        logger.error(f"Error saving to {table_name}: {e}")
        logger.error(traceback.format_exc())
        return False

def upload_to_supabase_storage(file, folder="products"):
    """Upload an image to Supabase Storage"""
    if not supabase:
        return None, "Supabase not available"
    
    try:
        timestamp = int(datetime.now().timestamp())
        safe_filename = secure_filename(file.filename)
        file_extension = os.path.splitext(safe_filename)[1]
        unique_filename = f"{folder}/{timestamp}_{uuid.uuid4().hex}{file_extension}"
        
        file.seek(0)
        file_data = file.read()
        content_type = file.content_type or 'image/jpeg'
        
        logger.info(f"Uploading to Supabase: {unique_filename} ({len(file_data)} bytes)")
        
        supabase.storage.from_(STORAGE_BUCKET).upload(
            path=unique_filename,
            file=file_data,
            file_options={"content-type": content_type}
        )
        
        logger.info(f"✓ Successfully uploaded to Supabase: {unique_filename}")
        
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(unique_filename)
        
        return {
            'path': unique_filename,
            'public_url': public_url,
            'proxy_url': f"/api/images/{unique_filename}"
        }, None
        
    except Exception as e:
        logger.error(f"Error uploading to Supabase: {e}")
        return None, str(e)

def delete_from_supabase_storage(path):
    """Delete an image from Supabase Storage"""
    if not supabase or not path:
        return False
    try:
        supabase.storage.from_(STORAGE_BUCKET).remove([path])
        logger.info(f"✓ Deleted from Supabase: {path}")
        return True
    except Exception as e:
        logger.error(f"Error deleting from Supabase: {e}")
        return False

# ==================== RECEIPT GENERATION FUNCTIONS ====================

def generate_receipt_pdf(sale_data, product_data):
    """Generate a formal PDF receipt for a sale"""
    try:
        receipt_id = f"RCP-{sale_data['id']}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        filename = f"receipts/{receipt_id}.pdf"
        
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a237e'),
            alignment=1,  # Center alignment
            spaceAfter=30
        )
        
        header_style = ParagraphStyle(
            'HeaderStyle',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#ff5722'),
            spaceAfter=12
        )
        
        # Add company logo/header
        story.append(Paragraph("KARANJA SHOE STORE", title_style))
        story.append(Paragraph("Official Sales Receipt", header_style))
        story.append(Spacer(1, 20))
        
        # Receipt details
        receipt_info = [
            [f"Receipt No: {receipt_id}"],
            [f"Date: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"],
            [f"Cashier: {CONSTANT_USER_NAME}"]
        ]
        
        for row in receipt_info:
            story.append(Paragraph(row[0], styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Customer info
        story.append(Paragraph("Customer Information", header_style))
        customer_info = [
            [f"Name: {sale_data.get('customerName', 'Walk-in Customer')}"],
            [f"Contact: {sale_data.get('customerPhone', 'N/A')}"]
        ]
        for row in customer_info:
            story.append(Paragraph(row[0], styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Product details table
        story.append(Paragraph("Product Details", header_style))
        
        table_data = [
            ['Description', 'Size', 'Quantity', 'Unit Price', 'Total']
        ]
        
        product_name = product_data.get('name', 'Unknown Product')
        size = sale_data.get('size', 'N/A')
        quantity = sale_data.get('quantity', 1)
        unit_price = sale_data.get('unitPrice', 0)
        total = sale_data.get('totalAmount', 0)
        
        table_data.append([
            product_name,
            str(size),
            str(quantity),
            f"KES {unit_price:,.2f}",
            f"KES {total:,.2f}"
        ])
        
        # Create table
        table = Table(table_data, colWidths=[2.5*inch, 0.8*inch, 0.8*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Payment summary
        story.append(Paragraph("Payment Summary", header_style))
        
        profit = sale_data.get('totalProfit', 0)
        is_bargain = sale_data.get('isBargain', False)
        
        summary_data = [
            ['Subtotal:', f"KES {total:,.2f}"],
            ['Discount:', 'KES 0.00'],
            ['Total Amount:', f"KES {total:,.2f}"],
            ['Profit Earned:', f"KES {profit:,.2f}"],
            ['Sale Type:', 'Bargain Sale' if is_bargain else 'Regular Sale']
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LINEABOVE', (0, -2), (-1, -2), 1, colors.black),
            ('LINEABOVE', (0, -1), (-1, -1), 2, colors.HexColor('#1a237e')),
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 30))
        
        # Footer with terms
        story.append(Paragraph("Terms & Conditions:", styles['Heading4']))
        story.append(Paragraph("1. This is a computer generated receipt", styles['Normal']))
        story.append(Paragraph("2. No returns after 7 days of purchase", styles['Normal']))
        story.append(Paragraph("3. Items must be in original condition for exchange", styles['Normal']))
        story.append(Spacer(1, 20))
        
        # Generate QR Code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr_data = f"""
        Receipt: {receipt_id}
        Amount: KES {total:,.2f}
        Date: {datetime.now().strftime('%d/%m/%Y')}
        Product: {product_name}
        """
        qr.add_data(qr_data)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format='PNG')
        qr_buffer.seek(0)
        
        qr_image = Image(qr_buffer, width=1*inch, height=1*inch)
        story.append(qr_image)
        
        story.append(Spacer(1, 10))
        story.append(Paragraph("Thank you for shopping with Karanja Shoe Store!", styles['Italic']))
        story.append(Paragraph("We appreciate your business!", styles['Italic']))
        
        # Build PDF
        doc.build(story)
        
        return filename, receipt_id
        
    except Exception as e:
        logger.error(f"Error generating receipt PDF: {e}")
        return None, None

def generate_daily_statement_pdf(date=None):
    """Generate daily sales statement PDF"""
    try:
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        statement_id = f"STM-{date}-{datetime.now().strftime('%H%M%S')}"
        filename = f"statements/{statement_id}.pdf"
        
        # Get sales for the day
        sales = get_table_data('sales')
        daily_sales = [s for s in sales if s.get('timestamp', '').startswith(date)]
        
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=22,
            textColor=colors.HexColor('#1a237e'),
            alignment=1,
            spaceAfter=20
        )
        
        story.append(Paragraph("KARANJA SHOE STORE", title_style))
        story.append(Paragraph(f"Daily Sales Statement - {datetime.strptime(date, '%Y-%m-%d').strftime('%d %B %Y')}", 
                              styles['Heading2']))
        story.append(Spacer(1, 20))
        
        # Summary statistics
        total_sales = len(daily_sales)
        total_revenue = sum(s.get('totalamount', 0) for s in daily_sales)
        total_profit = sum(s.get('totalprofit', 0) for s in daily_sales)
        total_items = sum(s.get('quantity', 0) for s in daily_sales)
        
        summary_data = [
            ['Total Transactions:', str(total_sales)],
            ['Items Sold:', str(total_items)],
            ['Total Revenue:', f"KES {total_revenue:,.2f}"],
            ['Total Profit:', f"KES {total_profit:,.2f}"]
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('BACKGROUND', (0, -1), (1, -1), colors.HexColor('#4caf50')),
            ('TEXTCOLOR', (0, -1), (1, -1), colors.whitesmoke),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 30))
        
        # Sales details table
        if daily_sales:
            story.append(Paragraph("Transaction Details", styles['Heading3']))
            
            table_data = [['Time', 'Product', 'Size', 'Qty', 'Amount', 'Profit']]
            
            for sale in sorted(daily_sales, key=lambda x: x.get('timestamp', '')):
                time_str = sale.get('timestamp', '')[11:16] if sale.get('timestamp') else 'N/A'
                table_data.append([
                    time_str,
                    sale.get('productname', 'Unknown')[:20],
                    str(sale.get('size', 'N/A')),
                    str(sale.get('quantity', 0)),
                    f"KES {sale.get('totalamount', 0):,.0f}",
                    f"KES {sale.get('totalprofit', 0):,.0f}"
                ])
            
            table = Table(table_data, colWidths=[1*inch, 2.5*inch, 0.6*inch, 0.6*inch, 1.2*inch, 1.2*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey)
            ]))
            
            story.append(table)
        
        # Footer
        story.append(Spacer(1, 30))
        story.append(Paragraph(f"Statement generated on {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", 
                              styles['Italic']))
        
        doc.build(story)
        
        return filename, statement_id
        
    except Exception as e:
        logger.error(f"Error generating statement PDF: {e}")
        return None, None

def generate_monthly_report_pdf(year, month):
    """Generate monthly sales report PDF"""
    try:
        report_id = f"RPT-{year}{month:02d}-{datetime.now().strftime('%H%M%S')}"
        filename = f"reports/{report_id}.pdf"
        
        # Get sales for the month
        sales = get_table_data('sales')
        month_str = f"{year}-{month:02d}"
        monthly_sales = [s for s in sales if s.get('timestamp', '').startswith(month_str)]
        
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        story.append(Paragraph("KARANJA SHOE STORE", styles['Title']))
        story.append(Paragraph(f"Monthly Sales Report - {datetime(year, month, 1).strftime('%B %Y')}", 
                              styles['Heading2']))
        story.append(Spacer(1, 20))
        
        # Executive summary
        total_sales = len(monthly_sales)
        total_revenue = sum(s.get('totalamount', 0) for s in monthly_sales)
        total_profit = sum(s.get('totalprofit', 0) for s in monthly_sales)
        total_items = sum(s.get('quantity', 0) for s in monthly_sales)
        
        avg_transaction = total_revenue / total_sales if total_sales > 0 else 0
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        summary_data = [
            ['Metric', 'Value'],
            ['Total Transactions', str(total_sales)],
            ['Items Sold', str(total_items)],
            ['Total Revenue', f"KES {total_revenue:,.2f}"],
            ['Total Profit', f"KES {total_profit:,.2f}"],
            ['Average Transaction', f"KES {avg_transaction:,.2f}"],
            ['Profit Margin', f"{profit_margin:.1f}%"]
        ]
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a237e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 30))
        
        # Category analysis
        story.append(Paragraph("Category Performance", styles['Heading3']))
        
        categories = {}
        for sale in monthly_sales:
            cat = sale.get('category', 'Uncategorized')
            if cat not in categories:
                categories[cat] = {'revenue': 0, 'profit': 0, 'quantity': 0}
            categories[cat]['revenue'] += sale.get('totalamount', 0)
            categories[cat]['profit'] += sale.get('totalprofit', 0)
            categories[cat]['quantity'] += sale.get('quantity', 0)
        
        cat_data = [['Category', 'Units Sold', 'Revenue', 'Profit']]
        for cat, data in sorted(categories.items(), key=lambda x: x[1]['revenue'], reverse=True):
            cat_data.append([
                cat,
                str(data['quantity']),
                f"KES {data['revenue']:,.0f}",
                f"KES {data['profit']:,.0f}"
            ])
        
        cat_table = Table(cat_data, colWidths=[1.5*inch, 1*inch, 1.5*inch, 1.5*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ff5722')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey)
        ]))
        
        story.append(cat_table)
        
        doc.build(story)
        
        return filename, report_id
        
    except Exception as e:
        logger.error(f"Error generating monthly report: {e}")
        return None, None

# ==================== EMAIL FUNCTIONS ====================

def send_email_with_attachment(recipient_emails, subject, body, attachment_path, attachment_name=None):
    """Send email with PDF attachment to multiple recipients"""
    try:
        if attachment_name is None:
            attachment_name = os.path.basename(attachment_path)
        
        # Create message
        msg = MIMEMultipart()
        msg['From'] = EMAIL_CONFIG['sender_email']
        msg['To'] = ', '.join(recipient_emails)
        msg['Subject'] = subject
        
        # Add body
        msg.attach(MIMEText(body, 'html'))
        
        # Add attachment
        with open(attachment_path, 'rb') as f:
            attachment = MIMEApplication(f.read(), _subtype="pdf")
            attachment.add_header('Content-Disposition', 'attachment', filename=attachment_name)
            msg.attach(attachment)
        
        # Send email
        server = smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port'])
        server.starttls()
        server.login(EMAIL_CONFIG['sender_email'], EMAIL_CONFIG['sender_password'])
        server.send_message(msg)
        server.quit()
        
        logger.info(f"✓ Email sent to {', '.join(recipient_emails)}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False

# ==================== WHATSAPP FUNCTIONS ====================

def send_whatsapp_message(recipient, message, media_url=None):
    """Send WhatsApp message with optional media"""
    try:
        headers = {
            'Authorization': f'Bearer {WHATSAPP_CONFIG["access_token"]}',
            'Content-Type': 'application/json'
        }
        
        if media_url:
            # Send media message
            data = {
                'messaging_product': 'whatsapp',
                'to': recipient,
                'type': 'document',
                'document': {
                    'link': media_url,
                    'caption': message
                }
            }
        else:
            # Send text message
            data = {
                'messaging_product': 'whatsapp',
                'to': recipient,
                'type': 'text',
                'text': {'body': message}
            }
        
        response = requests.post(WHATSAPP_CONFIG['api_url'], headers=headers, json=data)
        
        if response.status_code == 200:
            logger.info(f"✓ WhatsApp message sent to {recipient}")
            return True
        else:
            logger.error(f"WhatsApp API error: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        return False

def format_whatsapp_receipt(sale_data, product_data, receipt_id):
    """Format receipt details for WhatsApp message"""
    total = sale_data.get('totalAmount', 0)
    profit = sale_data.get('totalProfit', 0)
    quantity = sale_data.get('quantity', 1)
    unit_price = sale_data.get('unitPrice', 0)
    size = sale_data.get('size', 'N/A')
    
    message = f"""
🏪 *KARANJA SHOE STORE* 🏪
━━━━━━━━━━━━━━━━━━━━━
📋 *SALE RECEIPT*
━━━━━━━━━━━━━━━━━━━━━

📌 *Receipt No:* {receipt_id}
📅 *Date:* {datetime.now().strftime('%d/%m/%Y %H:%M')}

👤 *Customer:* {sale_data.get('customerName', 'Walk-in Customer')}

━━━━━━━━━━━━━━━━━━━━━
🛍️ *PRODUCT DETAILS*
━━━━━━━━━━━━━━━━━━━━━

📦 *Product:* {product_data.get('name', 'Unknown')}
📏 *Size:* {size}
🎨 *Color:* {product_data.get('color', 'N/A')}
🔢 *Quantity:* {quantity}
💰 *Unit Price:* KES {unit_price:,.2f}
💵 *Total:* KES {total:,.2f}

━━━━━━━━━━━━━━━━━━━━━
💹 *PROFIT SUMMARY*
━━━━━━━━━━━━━━━━━━━━━

📊 *Profit Earned:* KES {profit:,.2f}
🏷️ *Sale Type:* {'Bargain' if sale_data.get('isBargain') else 'Regular'}

━━━━━━━━━━━━━━━━━━━━━
✅ *Thank you for shopping with us!*
📍 *Karanja Shoe Store*
━━━━━━━━━━━━━━━━━━━━━
"""
    return message

def send_sale_notifications(sale_data, product_data, receipt_path, receipt_id):
    """Send sale notifications to email and WhatsApp"""
    try:
        # Prepare email body
        email_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #1a237e, #ff5722); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f5f5f5; padding: 20px; border-radius: 0 0 10px 10px; }}
                .details {{ background: white; padding: 15px; border-radius: 8px; margin: 10px 0; }}
                table {{ width: 100%; border-collapse: collapse; }}
                td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
                .total {{ font-size: 18px; font-weight: bold; color: #1a237e; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🏪 KARANJA SHOE STORE</h2>
                    <h3>New Sale Receipt</h3>
                </div>
                <div class="content">
                    <div class="details">
                        <h3>Receipt Details</h3>
                        <table>
                            <tr><td><strong>Receipt No:</strong></td><td>{receipt_id}</td></tr>
                            <tr><td><strong>Date:</strong></td><td>{datetime.now().strftime('%d/%m/%Y %H:%M')}</td></tr>
                            <tr><td><strong>Customer:</strong></td><td>{sale_data.get('customerName', 'Walk-in Customer')}</td></tr>
                        </table>
                    </div>
                    
                    <div class="details">
                        <h3>Product Information</h3>
                        <table>
                            <tr><td><strong>Product:</strong></td><td>{product_data.get('name', 'Unknown')}</td></tr>
                            <tr><td><strong>Size:</strong></td><td>{sale_data.get('size', 'N/A')}</td></tr>
                            <tr><td><strong>Color:</strong></td><td>{product_data.get('color', 'N/A')}</td></tr>
                            <tr><td><strong>Quantity:</strong></td><td>{sale_data.get('quantity', 1)}</td></tr>
                            <tr><td><strong>Unit Price:</strong></td><td>KES {sale_data.get('unitPrice', 0):,.2f}</td></tr>
                            <tr><td><strong>Total Amount:</strong></td><td class="total">KES {sale_data.get('totalAmount', 0):,.2f}</td></tr>
                            <tr><td><strong>Profit Earned:</strong></td><td class="total" style="color: #4caf50;">KES {sale_data.get('totalProfit', 0):,.2f}</td></tr>
                        </table>
                    </div>
                    
                    <p>Please find attached the official receipt PDF.</p>
                    <p><em>This is an automated notification from Karanja Shoe Store.</em></p>
                </div>
                <div class="footer">
                    <p>© 2026 Karanja Shoe Store. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Send to backup emails
        email_sent = send_email_with_attachment(
            recipient_emails=EMAIL_CONFIG['backup_emails'],
            subject=f"🏪 New Sale Receipt - {receipt_id}",
            body=email_body,
            attachment_path=receipt_path,
            attachment_name=f"{receipt_id}.pdf"
        )
        
        # Send WhatsApp messages
        whatsapp_message = format_whatsapp_receipt(sale_data, product_data, receipt_id)
        
        # Upload receipt to Supabase for WhatsApp link
        receipt_url = None
        if supabase:
            try:
                with open(receipt_path, 'rb') as f:
                    file_data = f.read()
                
                filename = f"receipts/{receipt_id}.pdf"
                supabase.storage.from_(STORAGE_BUCKET).upload(
                    path=filename,
                    file=file_data,
                    file_options={"content-type": "application/pdf"}
                )
                receipt_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(filename)
            except Exception as e:
                logger.error(f"Error uploading receipt to Supabase: {e}")
        
        for recipient in WHATSAPP_CONFIG['recipients']:
            send_whatsapp_message(
                recipient=recipient,
                message=whatsapp_message,
                media_url=receipt_url
            )
        
        return True
        
    except Exception as e:
        logger.error(f"Error sending notifications: {e}")
        return False

# ==================== IMAGE PROXY ====================

@app.route('/api/images/<path:image_path>')
def proxy_image(image_path):
    """Proxy images from Supabase storage"""
    if not supabase:
        return send_file('static/placeholder.png')
    try:
        public_url = supabase.storage.from_(STORAGE_BUCKET).get_public_url(image_path)
        if public_url:
            response = requests.get(public_url, timeout=10)
            if response.status_code == 200:
                resp = make_response(response.content)
                resp.headers['Content-Type'] = response.headers.get('Content-Type', 'image/jpeg')
                resp.headers['Cache-Control'] = 'public, max-age=3600'
                return resp
        return send_file('static/placeholder.png')
    except Exception as e:
        logger.error(f"Error proxying image: {e}")
        return send_file('static/placeholder.png')

# ==================== AUTH ROUTES ====================

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Authenticate user with constant credentials"""
    try:
        data = request.get_json()
        email = data.get('email', '').upper()
        password = data.get('password', '')
        
        if email == CONSTANT_EMAIL and password == CONSTANT_PASSWORD:
            access_token = create_access_token(
                identity=CONSTANT_USER_ID,
                additional_claims={
                    'email': CONSTANT_EMAIL,
                    'name': CONSTANT_USER_NAME,
                    'role': CONSTANT_USER_ROLE
                }
            )
            
            return jsonify({
                'success': True,
                'token': access_token,
                'user': {
                    'id': CONSTANT_USER_ID,
                    'email': CONSTANT_EMAIL,
                    'name': CONSTANT_USER_NAME,
                    'role': CONSTANT_USER_ROLE
                }
            }), 200
        
        return jsonify({'error': 'Invalid credentials'}), 401
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== RECEIPT DOWNLOAD ROUTES ====================

@app.route('/api/receipts/<receipt_id>', methods=['GET'])
@jwt_required()
def download_receipt(receipt_id):
    """Download a receipt by ID"""
    try:
        receipt_path = f"receipts/{receipt_id}.pdf"
        if os.path.exists(receipt_path):
            return send_file(receipt_path, as_attachment=True, download_name=f"{receipt_id}.pdf")
        return jsonify({'error': 'Receipt not found'}), 404
    except Exception as e:
        logger.error(f"Error downloading receipt: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/statements/<statement_id>', methods=['GET'])
@jwt_required()
def download_statement(statement_id):
    """Download a statement by ID"""
    try:
        statement_path = f"statements/{statement_id}.pdf"
        if os.path.exists(statement_path):
            return send_file(statement_path, as_attachment=True, download_name=f"{statement_id}.pdf")
        return jsonify({'error': 'Statement not found'}), 404
    except Exception as e:
        logger.error(f"Error downloading statement: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/<report_id>', methods=['GET'])
@jwt_required()
def download_report(report_id):
    """Download a report by ID"""
    try:
        report_path = f"reports/{report_id}.pdf"
        if os.path.exists(report_path):
            return send_file(report_path, as_attachment=True, download_name=f"{report_id}.pdf")
        return jsonify({'error': 'Report not found'}), 404
    except Exception as e:
        logger.error(f"Error downloading report: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/receipts/latest', methods=['GET'])
@jwt_required()
def get_latest_receipts():
    """Get list of latest receipts"""
    try:
        receipts = []
        if os.path.exists('receipts'):
            files = os.listdir('receipts')
            pdf_files = [f for f in files if f.endswith('.pdf')]
            pdf_files.sort(reverse=True)
            
            for filename in pdf_files[:20]:  # Last 20 receipts
                receipt_id = filename.replace('.pdf', '')
                file_path = os.path.join('receipts', filename)
                created = datetime.fromtimestamp(os.path.getctime(file_path))
                
                receipts.append({
                    'id': receipt_id,
                    'filename': filename,
                    'date': created.isoformat(),
                    'size': os.path.getsize(file_path),
                    'url': f"/api/receipts/{receipt_id}"
                })
        
        return jsonify(receipts), 200
    except Exception as e:
        logger.error(f"Error getting receipts: {e}")
        return jsonify([]), 200

@app.route('/api/statements/latest', methods=['GET'])
@jwt_required()
def get_latest_statements():
    """Get list of latest statements"""
    try:
        statements = []
        if os.path.exists('statements'):
            files = os.listdir('statements')
            pdf_files = [f for f in files if f.endswith('.pdf')]
            pdf_files.sort(reverse=True)
            
            for filename in pdf_files[:20]:
                statement_id = filename.replace('.pdf', '')
                file_path = os.path.join('statements', filename)
                created = datetime.fromtimestamp(os.path.getctime(file_path))
                
                statements.append({
                    'id': statement_id,
                    'filename': filename,
                    'date': created.isoformat(),
                    'size': os.path.getsize(file_path),
                    'url': f"/api/statements/{statement_id}"
                })
        
        return jsonify(statements), 200
    except Exception as e:
        logger.error(f"Error getting statements: {e}")
        return jsonify([]), 200

@app.route('/api/reports/latest', methods=['GET'])
@jwt_required()
def get_latest_reports():
    """Get list of latest reports"""
    try:
        reports = []
        if os.path.exists('reports'):
            files = os.listdir('reports')
            pdf_files = [f for f in files if f.endswith('.pdf')]
            pdf_files.sort(reverse=True)
            
            for filename in pdf_files[:20]:
                report_id = filename.replace('.pdf', '')
                file_path = os.path.join('reports', filename)
                created = datetime.fromtimestamp(os.path.getctime(file_path))
                
                reports.append({
                    'id': report_id,
                    'filename': filename,
                    'date': created.isoformat(),
                    'size': os.path.getsize(file_path),
                    'url': f"/api/reports/{report_id}"
                })
        
        return jsonify(reports), 200
    except Exception as e:
        logger.error(f"Error getting reports: {e}")
        return jsonify([]), 200

# ==================== UPLOAD ROUTE ====================

@app.route('/api/supabase/upload', methods=['POST'])
@jwt_required()
def upload_to_supabase():
    """Upload image to Supabase Storage"""
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 503
    
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file'}), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({'error': 'No image selected'}), 400
        
        allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        if file.content_type not in allowed_types:
            return jsonify({'error': 'File type not allowed. Please upload an image.'}), 400
        
        result, error = upload_to_supabase_storage(file, "products")
        
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'url': f"/api/images/{result['path']}",
            'public_url': result['public_url'],
            'path': result['path']
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PRODUCT ROUTES ====================

@app.route('/api/products', methods=['GET'])
@jwt_required()
def get_products():
    """Get all products"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
        
        for product in products:
            if product.get('image_path'):
                product['image'] = f"/api/images/{product['image_path']}"
            product['buyPrice'] = product.get('buyprice', 0)
            product['minSellPrice'] = product.get('minsellprice', 0)
            product['maxSellPrice'] = product.get('maxsellprice', 0)
            product['totalStock'] = product.get('totalstock', 0)
            product['dateAdded'] = product.get('dateadded', '')
            product['lastUpdated'] = product.get('lastupdated', '')
        
        return jsonify(products), 200
    except Exception as e:
        logger.error(f"Error getting products: {e}")
        return jsonify([]), 200

@app.route('/api/products', methods=['POST'])
@jwt_required()
def create_product():
    """Create new product"""
    try:
        name = request.form.get('name')
        if not name:
            return jsonify({'error': 'Product name required'}), 400
        
        sku = request.form.get('sku', f"KS-{uuid.uuid4().hex[:8].upper()}")
        category = request.form.get('category', 'Uncategorized')
        color = request.form.get('color', '')
        description = request.form.get('description', '')
        
        sizes_json = request.form.get('sizes', '{}')
        try:
            sizes = json.loads(sizes_json)
        except:
            sizes = {}
        
        buy_price = float(request.form.get('buyPrice', 0))
        min_sell = float(request.form.get('minSellPrice', 0))
        max_sell = float(request.form.get('maxSellPrice', 0))
        image_path = request.form.get('image_path')
        
        total_stock = 0
        for stock in sizes.values():
            try:
                total_stock += int(stock) if stock and int(stock) > 0 else 0
            except:
                pass
        
        product_id = int(datetime.now().timestamp() * 1000)
        
        product = {
            'id': product_id,
            'name': name.strip(),
            'sku': sku,
            'category': category,
            'color': color,
            'description': description,
            'sizes': sizes,
            'buyprice': buy_price,
            'minsellprice': min_sell,
            'maxsellprice': max_sell,
            'price': max_sell,
            'totalstock': total_stock,
            'dateadded': datetime.now().isoformat(),
            'lastupdated': datetime.now().isoformat(),
            'image_path': image_path,
            'storage': 'supabase',
            'createdby': get_jwt_identity()
        }
        
        if save_table_data('products', product):
            product['buyPrice'] = buy_price
            product['minSellPrice'] = min_sell
            product['maxSellPrice'] = max_sell
            product['totalStock'] = total_stock
            product['dateAdded'] = product['dateadded']
            product['lastUpdated'] = product['lastupdated']
            
            if image_path:
                product['image'] = f"/api/images/{image_path}"
            
            logger.info(f"✓ Product created: {name}")
            return jsonify({'success': True, 'product': product}), 201
        else:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
    except Exception as e:
        logger.error(f"Error creating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    """Update existing product"""
    try:
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        if request.form.get('name'):
            product['name'] = request.form['name'].strip()
        if request.form.get('category'):
            product['category'] = request.form['category']
        if request.form.get('color'):
            product['color'] = request.form['color']
        if request.form.get('description'):
            product['description'] = request.form['description']
        if request.form.get('buyPrice'):
            product['buyprice'] = float(request.form['buyPrice'])
        if request.form.get('minSellPrice'):
            product['minsellprice'] = float(request.form['minSellPrice'])
        if request.form.get('maxSellPrice'):
            product['maxsellprice'] = float(request.form['maxSellPrice'])
            product['price'] = float(request.form['maxSellPrice'])
        
        if request.form.get('sizes'):
            try:
                sizes = json.loads(request.form['sizes'])
                product['sizes'] = sizes
                
                total_stock = 0
                for stock in sizes.values():
                    try:
                        total_stock += int(stock) if stock and int(stock) > 0 else 0
                    except:
                        pass
                product['totalstock'] = total_stock
            except:
                pass
        
        if request.form.get('image_path'):
            if product.get('image_path'):
                delete_from_supabase_storage(product['image_path'])
            product['image_path'] = request.form['image_path']
        
        product['lastupdated'] = datetime.now().isoformat()
        
        if save_table_data('products', product):
            product['buyPrice'] = product.get('buyprice', 0)
            product['minSellPrice'] = product.get('minsellprice', 0)
            product['maxSellPrice'] = product.get('maxsellprice', 0)
            product['totalStock'] = product.get('totalstock', 0)
            product['dateAdded'] = product.get('dateadded', '')
            product['lastUpdated'] = product.get('lastupdated', '')
            
            if product.get('image_path'):
                product['image'] = f"/api/images/{product['image_path']}"
            
            return jsonify({'success': True, 'product': product}), 200
        else:
            return jsonify({'error': 'Failed to save to Supabase'}), 500
        
    except Exception as e:
        logger.error(f"Error updating product: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    """Delete product"""
    try:
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        
        if product.get('image_path'):
            delete_from_supabase_storage(product['image_path'])
        
        if delete_table_data('products', product_id):
            return jsonify({'success': True}), 200
        else:
            return jsonify({'error': 'Failed to delete from Supabase'}), 500
        
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== PUBLIC PRODUCTS ====================

@app.route('/api/public/products', methods=['GET'])
def get_public_products():
    """Public endpoint for products (no auth required)"""
    try:
        products = get_table_data('products')
        products.sort(key=lambda x: x.get('dateadded', ''), reverse=True)
        
        public_products = []
        for product in products:
            public_product = {
                'id': product['id'],
                'name': product['name'],
                'sku': product.get('sku', ''),
                'category': product.get('category', ''),
                'color': product.get('color', ''),
                'description': product.get('description', ''),
                'price': product.get('price', 0),
                'totalStock': product.get('totalstock', 0),
                'sizes': product.get('sizes', {})
            }
            
            if product.get('image_path'):
                public_product['image'] = f"/api/images/{product['image_path']}"
                public_product['imageUrl'] = f"/api/images/{product['image_path']}"
            else:
                public_product['image'] = '/static/placeholder.png'
            
            public_products.append(public_product)
        
        return jsonify(public_products), 200
        
    except Exception as e:
        logger.error(f"Error getting public products: {e}")
        return jsonify([]), 200

# ==================== SALES ROUTES - WITH RECEIPT GENERATION ====================

@app.route('/api/sales', methods=['GET'])
@jwt_required()
def get_sales():
    """Get all sales"""
    try:
        sales = get_table_data('sales')
        sales.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        for sale in sales:
            sale['productId'] = sale.get('productid')
            sale['productName'] = sale.get('productname')
            sale['productSKU'] = sale.get('productsku')
            sale['buyPrice'] = sale.get('buyprice', 0)
            sale['unitPrice'] = sale.get('unitprice', 0)
            sale['totalAmount'] = sale.get('totalamount', 0)
            sale['totalProfit'] = sale.get('totalprofit', 0)
            sale['customerName'] = sale.get('customername', '')
            sale['isBargain'] = sale.get('isbargain', False)
            
            # Add receipt info if available
            receipt_id = f"RCP-{sale['id']}-{sale.get('timestamp', '')[:10].replace('-', '') if sale.get('timestamp') else ''}"
            sale['receiptUrl'] = f"/api/receipts/{receipt_id}" if os.path.exists(f"receipts/{receipt_id}.pdf") else None
        
        logger.info(f"Returning {len(sales)} sales records")
        return jsonify(sales), 200
    except Exception as e:
        logger.error(f"Error getting sales: {e}")
        return jsonify([]), 200

@app.route('/api/sales', methods=['POST'])
@jwt_required()
def create_sale():
    """Record new sale with receipt generation and notifications"""
    try:
        data = request.get_json()
        logger.info(f"Received sale data: {json.dumps(data)}")
        
        # Validate required fields
        product_id = data.get('productId') or data.get('productid')
        size = data.get('size')
        quantity = data.get('quantity')
        unit_price = data.get('unitPrice') or data.get('unitprice')
        
        if not all([product_id, size, quantity, unit_price]):
            missing = []
            if not product_id: missing.append('productId/productid')
            if not size: missing.append('size')
            if not quantity: missing.append('quantity')
            if not unit_price: missing.append('unitPrice/unitprice')
            return jsonify({'error': f'Missing required fields: {", ".join(missing)}'}), 400
        
        try:
            product_id = int(product_id)
            quantity = int(quantity)
            unit_price = float(unit_price)
        except ValueError as e:
            return jsonify({'error': f'Invalid number format: {str(e)}'}), 400
        
        # Get product
        products = get_table_data('products')
        product = None
        for p in products:
            if p['id'] == product_id:
                product = p
                break
        
        if not product:
            return jsonify({'error': f'Product not found with ID: {product_id}'}), 404
        
        logger.info(f"Found product: {product['name']}, current stock: {json.dumps(product.get('sizes', {}))}")
        
        # Check stock
        size_key = str(size)
        sizes = product.get('sizes', {})
        
        if size_key not in sizes:
            available_sizes = [s for s, stock in sizes.items() if stock > 0]
            return jsonify({
                'error': f'Size {size} not available for this product',
                'available_sizes': available_sizes
            }), 400
        
        current_stock = sizes.get(size_key, 0)
        if current_stock < quantity:
            return jsonify({
                'error': f'Insufficient stock. Only {current_stock} available in size {size}',
                'available_stock': current_stock
            }), 400
        
        # Update stock
        sizes[size_key] = current_stock - quantity
        
        total_stock = 0
        for stock in sizes.values():
            total_stock += stock if stock > 0 else 0
        product['totalstock'] = total_stock
        product['lastupdated'] = datetime.now().isoformat()
        
        # Save updated product
        logger.info(f"Updating product stock: new total stock = {total_stock}")
        if not save_table_data('products', product):
            logger.error("Failed to update product stock")
            return jsonify({'error': 'Failed to update product stock'}), 500
        
        # Calculate totals
        total_amount = unit_price * quantity
        total_cost = product.get('buyprice', 0) * quantity
        total_profit = total_amount - total_cost
        
        customer_name = data.get('customerName') or data.get('customername') or 'Walk-in Customer'
        notes = data.get('notes', '')
        is_bargain = data.get('isBargain') or data.get('isbargain') or False
        
        sale_id = int(datetime.now().timestamp() * 1000)
        timestamp = datetime.now().isoformat()
        
        sale = {
            'id': sale_id,
            'productid': product_id,
            'productname': product.get('name', ''),
            'productsku': product.get('sku', ''),
            'category': product.get('category', ''),
            'buyprice': float(product.get('buyprice', 0)),
            'size': size_key,
            'quantity': quantity,
            'unitprice': unit_price,
            'totalamount': total_amount,
            'totalprofit': total_profit,
            'customername': customer_name,
            'notes': notes,
            'isbargain': bool(is_bargain),
            'timestamp': timestamp
        }
        
        logger.info(f"Attempting to save sale: {json.dumps(sale, default=str)}")
        
        # Save sale
        if save_table_data('sales', sale):
            logger.info(f"✓ Sale recorded successfully: {product['name']} - {quantity} x Size {size} @ {unit_price}")
            
            # Generate receipt
            receipt_path, receipt_id = generate_receipt_pdf(sale, product)
            
            if receipt_path:
                logger.info(f"✓ Receipt generated: {receipt_id}")
                
                # Send notifications
                send_sale_notifications(sale, product, receipt_path, receipt_id)
            
            # Create notification
            notification = {
                'id': int(datetime.now().timestamp() * 1000) + 1,
                'message': f'Sale: {product["name"]} ({quantity} × Size {size}) - Receipt: {receipt_id}',
                'type': 'success',
                'timestamp': timestamp,
                'read': False
            }
            save_table_data('notifications', notification)
            
            # Prepare response
            response_sale = {
                'id': sale_id,
                'productId': product_id,
                'productName': product['name'],
                'productSKU': product.get('sku', ''),
                'category': product.get('category', ''),
                'buyPrice': float(product.get('buyprice', 0)),
                'size': size_key,
                'quantity': quantity,
                'unitPrice': unit_price,
                'totalAmount': total_amount,
                'totalProfit': total_profit,
                'customerName': customer_name,
                'notes': notes,
                'isBargain': bool(is_bargain),
                'timestamp': timestamp,
                'receiptUrl': f"/api/receipts/{receipt_id}" if receipt_path else None,
                'receiptId': receipt_id
            }
            
            return jsonify({
                'success': True,
                'sale': response_sale,
                'message': 'Sale recorded successfully with receipt',
                'receiptUrl': f"/api/receipts/{receipt_id}" if receipt_path else None
            }), 201
        else:
            logger.error("Failed to save sale record - save_table_data returned False")
            return jsonify({'error': 'Failed to save sale record'}), 500
        
    except Exception as e:
        logger.error(f"Error creating sale: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ==================== STATEMENT GENERATION ROUTES ====================

@app.route('/api/statements/generate/daily', methods=['POST'])
@jwt_required()
def generate_daily_statement():
    """Generate daily statement"""
    try:
        data = request.get_json()
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        statement_path, statement_id = generate_daily_statement_pdf(date)
        
        if statement_path:
            # Send to email
            send_email_with_attachment(
                recipient_emails=EMAIL_CONFIG['backup_emails'],
                subject=f"📊 Daily Statement - {date}",
                body=f"<h2>Daily Sales Statement</h2><p>Date: {date}</p><p>Please find attached the daily sales statement.</p>",
                attachment_path=statement_path,
                attachment_name=f"{statement_id}.pdf"
            )
            
            return jsonify({
                'success': True,
                'statementUrl': f"/api/statements/{statement_id}",
                'statementId': statement_id
            }), 200
        else:
            return jsonify({'error': 'Failed to generate statement'}), 500
            
    except Exception as e:
        logger.error(f"Error generating statement: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/generate/monthly', methods=['POST'])
@jwt_required()
def generate_monthly_report():
    """Generate monthly report"""
    try:
        data = request.get_json()
        year = data.get('year', datetime.now().year)
        month = data.get('month', datetime.now().month)
        
        report_path, report_id = generate_monthly_report_pdf(year, month)
        
        if report_path:
            month_name = datetime(year, month, 1).strftime('%B %Y')
            
            # Send to email
            send_email_with_attachment(
                recipient_emails=EMAIL_CONFIG['backup_emails'],
                subject=f"📈 Monthly Report - {month_name}",
                body=f"<h2>Monthly Sales Report</h2><p>Period: {month_name}</p><p>Please find attached the monthly sales report.</p>",
                attachment_path=report_path,
                attachment_name=f"{report_id}.pdf"
            )
            
            return jsonify({
                'success': True,
                'reportUrl': f"/api/reports/{report_id}",
                'reportId': report_id
            }), 200
        else:
            return jsonify({'error': 'Failed to generate report'}), 500
            
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== NOTIFICATION ROUTES ====================

@app.route('/api/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    """Get all notifications"""
    try:
        notifications = get_table_data('notifications')
        notifications.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return jsonify(notifications[:50]), 200
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return jsonify([]), 200

@app.route('/api/notifications/count', methods=['GET'])
@jwt_required()
def get_notification_count():
    """Get unread notification count"""
    try:
        notifications = get_table_data('notifications')
        unread_count = len([n for n in notifications if not n.get('read', False)])
        return jsonify({'count': unread_count}), 200
    except Exception as e:
        logger.error(f"Error getting notification count: {e}")
        return jsonify({'count': 0}), 200

@app.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@jwt_required()
def mark_notification_read(notification_id):
    """Mark notification as read"""
    try:
        notifications = get_table_data('notifications')
        for n in notifications:
            if n['id'] == notification_id:
                n['read'] = True
                save_table_data('notifications', n)
                break
        return jsonify({'success': True}), 200
    except Exception as e:
        logger.error(f"Error marking notification read: {e}")
        return jsonify({'error': str(e)}), 500

# ==================== DASHBOARD STATS ====================

@app.route('/api/dashboard/stats', methods=['GET'])
@jwt_required()
def get_dashboard_stats():
    """Get dashboard statistics"""
    try:
        products = get_table_data('products')
        sales = get_table_data('sales')
        
        total_products = len(products)
        total_stock = sum([p.get('totalstock', 0) for p in products])
        total_revenue = sum([s.get('totalamount', 0) for s in sales])
        total_profit = sum([s.get('totalprofit', 0) for s in sales])
        
        today = datetime.now().strftime('%Y-%m-%d')
        today_sales = [s for s in sales if s.get('timestamp', '').startswith(today)]
        today_revenue = sum([s.get('totalamount', 0) for s in today_sales])
        today_profit = sum([s.get('totalprofit', 0) for s in today_sales])
        today_items = sum([s.get('quantity', 0) for s in today_sales])
        
        # Count receipts
        receipt_count = len([f for f in os.listdir('receipts') if f.endswith('.pdf')]) if os.path.exists('receipts') else 0
        
        return jsonify({
            'totalProducts': total_products,
            'totalStock': total_stock,
            'totalRevenue': total_revenue,
            'totalProfit': total_profit,
            'todayRevenue': today_revenue,
            'todayProfit': today_profit,
            'todayItems': today_items,
            'salesCount': len(sales),
            'receiptCount': receipt_count,
            'storage_type': 'supabase'
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
            'receiptCount': 0,
            'storage_type': 'supabase'
        }), 200

# ==================== STORAGE INFO ====================

@app.route('/api/storage/info', methods=['GET'])
@jwt_required()
def get_storage_info():
    """Get storage information"""
    return jsonify({
        'provider': 'supabase',
        'bucket': STORAGE_BUCKET,
        'connected': SUPABASE_AVAILABLE,
        'storage_type': 'supabase'
    }), 200

# ==================== DEBUG ENDPOINTS ====================

@app.route('/api/debug/sales-table', methods=['GET'])
@jwt_required()
def debug_sales_table():
    """Debug endpoint to check sales table structure"""
    if not supabase:
        return jsonify({'error': 'Supabase not connected'}), 503
    
    results = {
        'table_exists': False,
        'columns': [],
        'can_select': False,
        'can_insert': False,
        'error_details': None
    }
    
    try:
        try:
            response = supabase.table('sales').select('*').limit(1).execute()
            results['table_exists'] = True
            results['can_select'] = True
            if hasattr(response, 'data'):
                results['sample_data'] = response.data
        except Exception as e:
            results['select_error'] = str(e)
        
        try:
            test_id = int(datetime.now().timestamp())
            test_sale = {
                'id': test_id,
                'productid': 999999,
                'productname': 'Test Product',
                'quantity': 1,
                'unitprice': 100,
                'totalamount': 100,
                'timestamp': datetime.now().isoformat()
            }
            
            insert_result = supabase.table('sales').insert(test_sale).execute()
            results['can_insert'] = True
            
            supabase.table('sales').delete().eq('id', test_id).execute()
        except Exception as e:
            results['insert_error'] = str(e)
            results['can_insert'] = False
            results['error_details'] = traceback.format_exc()
        
        return jsonify(results), 200
        
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500

@app.route('/api/debug/test-supabase', methods=['GET'])
@jwt_required()
def test_supabase():
    """Test Supabase connection and tables"""
    results = {
        'supabase_available': SUPABASE_AVAILABLE,
        'tables': {}
    }
    
    if not supabase:
        return jsonify(results), 200
    
    for table in ['products', 'sales', 'notifications']:
        try:
            response = supabase.table(table).select('*').limit(1).execute()
            results['tables'][table] = {
                'exists': True,
                'count': len(response.data) if hasattr(response, 'data') else 0
            }
        except Exception as e:
            results['tables'][table] = {
                'exists': False,
                'error': str(e)
            }
    
    return jsonify(results), 200

# ==================== HEALTH CHECK ====================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    product_count = 0
    sale_count = 0
    receipt_count = 0
    try:
        products = get_table_data('products')
        product_count = len(products)
        sales = get_table_data('sales')
        sale_count = len(sales)
        receipt_count = len([f for f in os.listdir('receipts') if f.endswith('.pdf')]) if os.path.exists('receipts') else 0
    except:
        pass
        
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
        'products': product_count,
        'sales': sale_count,
        'receipts': receipt_count,
        'storage_type': 'supabase'
    }), 200

@app.route('/api/public/health', methods=['GET'])
def public_health():
    """Public health check endpoint (no auth)"""
    return jsonify({
        'status': 'online',
        'message': 'Karanja Shoe Store API is running',
        'timestamp': datetime.now().isoformat()
    }), 200

# ==================== STATIC FILE SERVING ====================

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files"""
    try:
        return send_from_directory('static', filename)
    except Exception as e:
        return jsonify({'error': 'File not found'}), 404

# ==================== INDEX ROUTE ====================

@app.route('/')
def index():
    """Serve index.html"""
    try:
        if os.path.exists('index.html'):
            return send_file('index.html')
        return jsonify({
            'message': 'Karanja Shoe Store API is running',
            'supabase': 'connected' if SUPABASE_AVAILABLE else 'disconnected',
            'status': 'online'
        })
    except Exception as e:
        return jsonify({'error': 'Could not load index'}), 500

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Internal server error'}), 500

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info("KARANJA SHOE STORE - ENHANCED VERSION WITH RECEIPTS")
    logger.info("=" * 60)
    logger.info(f"Supabase URL: {SUPABASE_URL}")
    logger.info(f"Storage Bucket: {STORAGE_BUCKET}")
    logger.info(f"Connection: {'✓ Connected' if SUPABASE_AVAILABLE else '✗ Failed'}")
    logger.info("=" * 60)
    logger.info("Receipts Folder: receipts/")
    logger.info("Statements Folder: statements/")
    logger.info("Reports Folder: reports/")
    logger.info("=" * 60)
    logger.info(f"Backup Emails: {', '.join(EMAIL_CONFIG['backup_emails'])}")
    logger.info(f"WhatsApp Recipients: {', '.join(WHATSAPP_CONFIG['recipients'])}")
    logger.info("=" * 60)
    logger.info(f"Server starting on port {port}")
    logger.info("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=True)
