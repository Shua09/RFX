# src/features/procurement_assistant/services/supplier_matching_service.py
import json
import secrets
import string
import smtplib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional
from email.message import EmailMessage
from email.utils import formataddr
from ....common.db_pyodbc import get_db_connection
from ....common.logging_config import get_logger
from ....common.config import Config  # Import Config
from ..utils.security import AccessCodeGenerator

logger = get_logger(__name__)

class SupplierMatchingService:
    def __init__(self):
        self.connection = None
        self.cursor = None
        # Load email configuration from Config
        # Note: You'll need to add these to your config.py
        self.smtp_host = getattr(Config, 'SMTP_HOST', None)
        self.smtp_port = getattr(Config, 'SMTP_PORT', 587)
        self.smtp_user = getattr(Config, 'SMTP_EMAIL', None)
        self.smtp_pass = getattr(Config, 'SMTP_PASSWORD', None)
        self.sender_name = getattr(Config, 'SENDER_NAME', 'Procurement Department')
        self.base_url = getattr(Config, 'APP_BASE_URL', 'https://yourdomain.com')
        self.auto_match_suppliers = getattr(Config, 'AUTO_MATCH_SUPPLIERS', 'true').lower() == 'true'
        self.email_test_mode = getattr(Config, 'EMAIL_TEST_MODE', 'true').lower() == 'true'
        
    def __enter__(self):
        self.connection = get_db_connection()
        self.cursor = self.connection.cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            
    def generate_passcode(self) -> str:
        while True:
            chars = string.ascii_uppercase + string.digits
            part1 = ''.join(secrets.choice(chars) for _ in range(4))   
            part2 = ''.join(secrets.choice(chars) for _ in range(4))   
            passcode = f"RFQ-{part1}-{part2}"
            
            self.cursor.execute("""
                SELECT COUNT(*) FROM [RFQ].[rfq_suppliers]
                WHERE passcode = ?                
                """, (passcode,))
            
            if self.cursor.fetchone()[0] == 0:
                return passcode
    
    def calculate_match_score(self, supplier: Tuple, rfq_items: List) -> Dict[str, Any]:
        """
        Calculate how well a supplier matches the RFQ items
        Only considers items that are relevant to the supplier's categories
        """
        # Get all fields from supplier tuple
        supplier_id = supplier[0]
        company_name = supplier[1]
        brand_repr_json = supplier[2]
        categories_json = supplier[3]
        
        # Parse JSON fields
        try:
            brands = json.loads(brand_repr_json) if brand_repr_json else []
            categories = json.loads(categories_json) if categories_json else []
        except:
            brands = []
            categories = []
        
        # Also get supplier's actual products for better matching
        self.cursor.execute("""
            SELECT category, brand FROM [RFQ].[supplier_products]
            WHERE supplier_id = ? AND is_available = 1
        """, (supplier_id,))
        
        product_data = self.cursor.fetchall()
        
        # Add product categories and brands to the sets
        for prod in product_data:
            if prod[0] and prod[0] not in categories:
                categories.append(prod[0])
            if prod[1] and prod[1] not in brands:
                brands.append(prod[1])
        
        logger.info(f"--- Matching for supplier: {company_name} (ID: {supplier_id}) ---")
        logger.info(f"Supplier categories: {categories}")
        logger.info(f"Supplier brands: {brands}")
        
        # Convert to lowercase for case-insensitive matching
        brands_lower = [str(b).lower() for b in brands if b]
        categories_lower = [str(c).lower() for c in categories if c]
        
        # Determine which items are relevant to this supplier
        relevant_items = []
        non_relevant_items = []
        
        for item in rfq_items:
            line_number = item[0]
            category = item[1] if len(item) > 1 else ""
            brand = item[2] if len(item) > 2 else ""
            
            # Check if this item is relevant to the supplier
            is_relevant = False
            
            if category and categories_lower:
                category_lower = category.lower().strip()
                for supplier_cat in categories_lower:
                    if (supplier_cat == category_lower or 
                        supplier_cat in category_lower or 
                        category_lower in supplier_cat):
                        is_relevant = True
                        break
            
            if brand and brands_lower and not is_relevant:
                brand_lower = brand.lower().strip()
                for supplier_brand in brands_lower:
                    if (supplier_brand == brand_lower or 
                        supplier_brand in brand_lower or 
                        brand_lower in supplier_brand):
                        is_relevant = True
                        break
            
            if is_relevant:
                relevant_items.append(item)
            else:
                non_relevant_items.append({
                    "line_number": line_number,
                    "category": category,
                    "brand": brand,
                    "reason": "Not in supplier's product categories"
                })
        
        logger.info(f"Found {len(relevant_items)} relevant items out of {len(rfq_items)} total")
        
        # Now calculate match score based ONLY on relevant items
        matching_items = []
        partial_items = []
        missing_items = []
        
        relevant_count = len(relevant_items)
        matched_count = 0
        partial_count = 0
        
        for item in relevant_items:
            line_number = item[0]
            category = item[1]
            brand = item[2]
            quantity = item[3]
            specs_json = item[4] if len(item) > 4 else "{}"
            description = item[5] if len(item) > 5 else ""
            
            # Parse specifications
            try:
                specifications = json.loads(specs_json) if specs_json else {}
            except:
                specifications = {}
            
            item_info = {
                "line_number": line_number,
                "category": category,
                "brand": brand,
                "quantity": quantity,
                "description": description,
                "specifications": specifications
            }
            
            # Check category match
            category_match = False
            if category and categories_lower:
                category_lower = category.lower().strip()
                for supplier_cat in categories_lower:
                    if (supplier_cat == category_lower or 
                        supplier_cat in category_lower or 
                        category_lower in supplier_cat):
                        category_match = True
                        break
            
            # Check brand match
            brand_match = False
            if brand and brands_lower:
                brand_lower = brand.lower().strip()
                for supplier_brand in brands_lower:
                    if (supplier_brand == brand_lower or 
                        supplier_brand in brand_lower or 
                        brand_lower in supplier_brand):
                        brand_match = True
                        break
            
            # Check if this specific product exists in supplier_products
            exact_product_match = False
            if category and brand:
                self.cursor.execute("""
                    SELECT COUNT(*) FROM [RFQ].[supplier_products]
                    WHERE supplier_id = ? 
                    AND LOWER(category) LIKE ? 
                    AND LOWER(brand) LIKE ?
                    AND is_available = 1
                """, (
                    supplier_id,
                    f'%{category.lower()}%',
                    f'%{brand.lower()}%'
                ))
                if self.cursor.fetchone()[0] > 0:
                    exact_product_match = True
            
            if exact_product_match or (category_match and brand_match):
                matching_items.append(item_info)
                matched_count += 1
            elif category_match or brand_match:
                partial_items.append(item_info)
                partial_count += 1
            else:
                missing_items.append(item_info)
        
        # Calculate score based ONLY on relevant items
        if relevant_count > 0:
            total_points = relevant_count * 100
            earned_points = (matched_count * 100) + (partial_count * 50)
            match_score = (earned_points / total_points) * 100
        else:
            match_score = 0
        
        # Add information about non-relevant items
        summary = f"Matched {matched_count} of {relevant_count} relevant items fully, {partial_count} partially. {len(non_relevant_items)} items not in your product categories."
        
        logger.info(f"Match score for {company_name}: {match_score}% (based on {relevant_count} relevant items)")
        logger.info(f"  - Exact matches: {matched_count}")
        logger.info(f"  - Partial matches: {partial_count}")
        logger.info(f"  - Missing from relevant: {len(missing_items)}")
        logger.info(f"  - Non-relevant items skipped: {len(non_relevant_items)}")
        
        return {
            "match_score": round(match_score, 2),
            "matching_items": matching_items,
            "partial_items": partial_items,
            "missing_items": missing_items,
            "non_relevant_items": non_relevant_items,
            "summary": summary,
            "relevant_items_count": relevant_count,
            "total_items_count": len(rfq_items)
        }
    
    def find_matching_suppliers(self, rfq_id: str, min_match_score: float = 30.0) -> Dict[str, Any]:
        """
        Find suppliers that match the RFQ items
        Generates both access_code (for URL) and passcode (for second factor)
        """
        try:
            # Get RFQ items - include description field
            self.cursor.execute("""
                SELECT line_number, category, brand, quantity, specifications, description
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (rfq_id,))
            
            rfq_items = self.cursor.fetchall()
            
            if not rfq_items:
                return {
                    "status": "error",
                    "message": "No items found in RFQ"
                }
            
            # Debug: Log the structure of rfq_items
            logger.info(f"RFQ Items count: {len(rfq_items)}")
            for i, item in enumerate(rfq_items):
                logger.info(f"Item {i} - Line {item[0]}: {item[1]} {item[2]}, Qty: {item[3]}")
            
            # Get all active suppliers
            self.cursor.execute("""
                SELECT supplier_id, company_name, brand_representation, 
                    product_categories, email, alternate_email, 
                    contact_person, phone, website, city, country, rating
                FROM [RFQ].[suppliers]
                WHERE is_active = 1
                ORDER BY rating DESC
            """)
            
            suppliers = self.cursor.fetchall()
            
            logger.info(f"Found {len(suppliers)} active suppliers")
            
            matches = []
            
            # Match each supplier against RFQ items
            for supplier in suppliers:
                # Use the improved calculate_match_score that considers relevant items
                match_result = self.calculate_match_score(supplier, rfq_items)
                
                logger.info(f"Supplier {supplier[1]} match score: {match_result['match_score']}% (relevant: {match_result.get('relevant_items_count', 0)}/{match_result.get('total_items_count', len(rfq_items))})")
                
                if match_result['match_score'] >= min_match_score:
                    # Generate unique access code (for URL)
                    raw_access_code = AccessCodeGenerator.generate_access_code()
                    
                    # Generate unique passcode (for second factor)
                    passcode = self.generate_passcode()
                    
                    # Convert match details to JSON for storage
                    matching_items_json = json.dumps(match_result.get('matching_items', []))
                    partial_items_json = json.dumps(match_result.get('partial_items', []))
                    non_matching_items_json = json.dumps(match_result.get('missing_items', []))
                    non_relevant_items_json = json.dumps(match_result.get('non_relevant_items', []))
                    
                    # Store in database with matching data
                    self.cursor.execute("""
                        INSERT INTO [RFQ].[rfq_suppliers]
                        (rfq_id, supplier_id, access_code, passcode, match_score, status, created_at,
                        matching_items_json, partial_items_json, non_matching_items_json, non_relevant_items_json)
                        OUTPUT INSERTED.mapping_id
                        VALUES (?, ?, ?, ?, ?, 'PENDING', GETDATE(), ?, ?, ?, ?)
                    """, (
                        rfq_id, 
                        supplier[0], 
                        raw_access_code, 
                        passcode, 
                        match_result['match_score'],
                        matching_items_json, 
                        partial_items_json, 
                        non_matching_items_json,
                        non_relevant_items_json
                    ))
                    
                    mapping_id = self.cursor.fetchone()[0]
                    
                    # Generate encrypted version for URL
                    encrypted_code = AccessCodeGenerator.encrypt_access_code(raw_access_code)
                    
                    matches.append({
                        "mapping_id": mapping_id,
                        "supplier_id": supplier[0],
                        "company_name": supplier[1],
                        "contact_person": supplier[6],
                        "email": supplier[4],
                        "alternate_email": supplier[5],
                        "phone": supplier[7],
                        "website": supplier[8],
                        "location": f"{supplier[9]}, {supplier[10]}" if supplier[9] else None,
                        "rating": float(supplier[11]) if supplier[11] else None,
                        "match_score": match_result['match_score'],
                        "access_code": raw_access_code,  # For internal use
                        "encrypted_code": encrypted_code,  # For URL
                        "passcode": passcode,  # Second factor (to be entered)
                        "access_link": f"{self.base_url}/supplier/{encrypted_code}",  # Full URL
                        "match_details": {
                            "matching_items": match_result['matching_items'],
                            "partial_items": match_result['partial_items'],
                            "missing_items": match_result['missing_items'],
                            "non_relevant_items": match_result.get('non_relevant_items', []),
                            "summary": match_result['summary'],
                            "relevant_items_count": match_result.get('relevant_items_count', 0),
                            "total_items_count": match_result.get('total_items_count', len(rfq_items))
                        }
                    })
                    
                    logger.info(f"✅ Added supplier {supplier[1]} with mapping_id {mapping_id}")
            
            self.connection.commit()
            
            # Sort by match score (highest first) and rating
            matches.sort(key=lambda x: (x['match_score'], x['rating'] or 0), reverse=True)
            
            logger.info(f"Final result: Found {len(matches)} matching suppliers for RFQ {rfq_id}")
            
            return {
                "status": "success",
                "rfq_id": rfq_id,
                "total_suppliers_found": len(matches),
                "matches": matches
            }
            
        except Exception as e:
            logger.error(f"Error finding matching suppliers: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "message": str(e)
            }
            
    def validate_supplier_access(self, encrypted_code: str) -> Dict[str, Any]:
        """
        Validate supplier access using encrypted code
        This is called when supplier visits /rfq/suppliers/<encrypted_code>
        """
        try:
            # Validate and decrypt the code
            is_valid, raw_access_code = AccessCodeGenerator.validate_encrypted_code(encrypted_code)
            
            if not is_valid or not raw_access_code:
                return {
                    "status": "error",
                    "message": "Invalid access link"
                }
            
            # Look up the supplier with this access code
            self.cursor.execute("""
                SELECT rs.mapping_id, rs.rfq_id, rs.access_code, rs.status,
                    rs.last_viewed, rs.submitted_at,
                    s.supplier_id, s.company_name, s.contact_person,
                    h.total_budget, h.currency, h.required_date, h.delivery_deadline,
                    (SELECT COUNT(*) FROM [RFQ].[rfq_line_items] WHERE rfq_id = rs.rfq_id) as item_count
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.access_code = ? AND rs.status != 'EXPIRED'
            """, (raw_access_code,))
            
            row = self.cursor.fetchone()
            if not row:
                return {
                    "status": "error",
                    "message": "Invalid or expired access link"
                }
            
            # Update last_viewed
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_suppliers]
                SET last_viewed = GETDATE()
                WHERE mapping_id = ?
            """, (row[0],))
            
            # If this is first view, update status to VIEWED
            if row[3] == 'PENDING' or row[3] == 'EMAIL_SENT':
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET status = 'VIEWED'
                    WHERE mapping_id = ? AND status IN ('PENDING', 'EMAIL_SENT')
                """, (row[0],))
            
            self.connection.commit()
            
            # Get RFQ items to display
            self.cursor.execute("""
                SELECT line_number, category, brand, quantity, specifications
                FROM [RFQ].[rfq_line_items]
                WHERE rfq_id = ?
                ORDER BY line_number
            """, (row[1],))
            
            items = []
            for item in self.cursor.fetchall():
                items.append({
                    "line_number": item[0],
                    "category": item[1],
                    "brand": item[2],
                    "quantity": item[3],
                    "specifications": json.loads(item[4]) if item[4] else {}
                })
            
            return {
                "status": "success",
                "mapping_id": row[0],
                "rfq_id": row[1],
                "supplier_id": row[6],
                "company_name": row[7],
                "contact_person": row[8],
                "budget": float(row[9]) if row[9] else None,
                "currency": row[10],
                "required_date": row[11].isoformat() if row[11] else None,
                "delivery_deadline": row[12].isoformat() if row[12] else None,
                "item_count": row[13],
                "items": items,
                "has_submitted": row[5] is not None,
                "submitted_at": row[5].isoformat() if row[5] else None
            }
            
        except Exception as e:
            logger.error(f"Error validating supplier access: {str(e)}")
            return {
                "status": "error",
                "message": "Invalid access link"
            }
    
    def generate_email_content(self, mapping_id: int) -> Dict[str, Any]:
        """Generate email with both access link and passcode, showing only relevant items for this supplier"""
        
        # Get mapping details including RFQ items and supplier's matching info
        self.cursor.execute("""
            SELECT 
                rs.rfq_id, 
                rs.access_code, 
                rs.passcode, 
                rs.match_score,
                s.company_name, 
                s.contact_person, 
                s.email,
                s.supplier_id,
                s.brand_representation,
                s.product_categories,
                h.total_budget, 
                h.currency, 
                h.required_date, 
                h.delivery_deadline,
                h.created_at,
                DATEADD(day, 14, h.created_at) as expiry_date
            FROM [RFQ].[rfq_suppliers] rs
            JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
            JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
            WHERE rs.mapping_id = ?
        """, (mapping_id,))
        
        data = self.cursor.fetchone()
        
        if not data:
            return {
                "status": "error",
                "message": f"No mapping found for ID {mapping_id}"
            }
        
        # Parse supplier's brands and categories
        try:
            supplier_brands = json.loads(data[8]) if data[8] else []
            supplier_categories = json.loads(data[9]) if data[9] else []
        except:
            supplier_brands = []
            supplier_categories = []
        
        # Convert to lowercase for matching
        supplier_brands_lower = [str(b).lower() for b in supplier_brands if b]
        supplier_categories_lower = [str(c).lower() for c in supplier_categories if c]
        
        # Get ALL RFQ items for this RFQ
        self.cursor.execute("""
            SELECT line_number, category, brand, quantity, description, specifications
            FROM [RFQ].[rfq_line_items]
            WHERE rfq_id = ?
            ORDER BY line_number
        """, (data[0],))  # data[0] is rfq_id
        
        all_items = self.cursor.fetchall()
        
        # Filter items that match this supplier
        matching_items = []
        other_items = []
        
        for item in all_items:
            line_number, category, brand, quantity, description, specs = item
            
            # Check if this item matches supplier's categories or brands
            category_match = False
            if category and supplier_categories_lower:
                category_lower = category.lower()
                for sc in supplier_categories_lower:
                    if sc in category_lower or category_lower in sc:
                        category_match = True
                        break
            
            brand_match = False
            if brand and supplier_brands_lower:
                brand_lower = brand.lower()
                for sb in supplier_brands_lower:
                    if sb in brand_lower or brand_lower in sb or sb == brand_lower:
                        brand_match = True
                        break
            
            if category_match or brand_match:
                matching_items.append(item)
            else:
                other_items.append(item)
        
        # Generate encrypted code for URL
        encrypted_code = AccessCodeGenerator.encrypt_access_code(data[1])  # access_code
        
        # Create access link
        access_link = f"{self.base_url}/supplier/{encrypted_code}"
        
        # Format expiry date
        expiry_date = data[15]  # expiry_date from query
        expiry_str = expiry_date.strftime("%B %d, %Y") if expiry_date else "14 days from now"
        
        # Build items table HTML - only show matching items
        items_html = ""
        items_text = ""
        
        if matching_items:
            # HTML table
            items_html = """
            <h3>🛒 Items You Can Quote For</h3>
            <table style="width:100%; border-collapse: collapse; margin: 20px 0;">
                <thead>
                    <tr style="background-color: #4CAF50; color: white;">
                        <th style="padding: 10px; text-align: left;">Line #</th>
                        <th style="padding: 10px; text-align: left;">Category</th>
                        <th style="padding: 10px; text-align: left;">Brand</th>
                        <th style="padding: 10px; text-align: right;">Quantity</th>
                        <th style="padding: 10px; text-align: left;">Description</th>
                    </tr>
                </thead>
                <tbody>
            """
            
            # Text version
            items_text = "\nITEMS YOU CAN QUOTE FOR:\n"
            items_text += "-" * 60 + "\n"
            
            for item in matching_items:
                line_number, category, brand, quantity, description, specs = item
                brand_str = brand if brand else "Any brand"
                
                # HTML row
                items_html += f"""
                    <tr style="border-bottom: 1px solid #ddd;">
                        <td style="padding: 8px;">{line_number}</td>
                        <td style="padding: 8px;">{category}</td>
                        <td style="padding: 8px;">{brand_str}</td>
                        <td style="padding: 8px; text-align: right;">{quantity}</td>
                        <td style="padding: 8px;">{description if description else ''}</td>
                    </tr>
                """
                
                # Text line
                items_text += f"  {line_number}. {category}"
                if brand:
                    items_text += f" - {brand}"
                items_text += f": {quantity} units"
                if description:
                    items_text += f" ({description})"
                items_text += "\n"
            
            items_html += """
                </tbody>
            </table>
            """
        else:
            items_html = "<p>No items matching your product categories were found in this RFX.</p>"
            items_text = "No items matching your product categories were found in this RFX."
        
        # Add note about other items (optional)
        if other_items:
            items_html += f"""
            <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 20px 0;">
                <p style="margin: 0; color: #856404;">
                    <strong>📋 Additional Items Notice:</strong><br>
                    This RFX contains <strong>{len(other_items)} other item(s)</strong> that fall outside your registered 
                    product categories or brands. You are not required to quote on these items, but you may still view them 
                    in the portal. You can choose to quote only for the items listed above that match your business.
                </p>
            </div>
            """
            items_text += f"""

        ╔════════════════════════════════════════════════════════════╗
        ║                    ADDITIONAL ITEMS NOTICE                 ║
        ╚════════════════════════════════════════════════════════════╝

        This RFX contains {len(other_items)} other item(s) that fall outside 
        your registered product categories or brands. You are NOT required 
        to quote on these items. You may quote only for the matching items 
        listed above.
        """
        
        # Format budget information
        budget_info = ""
        budget_text_line = ""

        if data[10] and data[11]:  # total_budget and currency
            try:
                budget_value = float(data[10])
                budget_formatted = f"{budget_value:,.2f}"
                budget_info = f"""
                <p><strong>Total RFX Budget:</strong> {data[11]} {budget_formatted}</p>
                <p><em><small>Note: This is the total budget for ALL items in the RFX, including items that may not match your company's categories.</small></em></p>
                """
                budget_text_line = f"Total RFX Budget: {data[11]} {budget_formatted} (for all items in the RFX)"
            except (ValueError, TypeError):
                budget_info = "<p><strong>Total RFX Budget:</strong> Not specified</p>"
                budget_text_line = "Total RFX Budget: Not specified"
        else:
            budget_info = "<p><strong>Total RFX Budget:</strong> Not specified</p>"
            budget_text_line = "Total RFX Budget: Not specified"
        
        # Format dates
        required_date = data[12].strftime("%B %d, %Y") if data[12] else "Not specified"
        delivery_deadline = data[13].strftime("%B %d, %Y") if data[13] else "Not specified"
        
        # Email HTML with clear instructions and filtered items
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                .container {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; background-color: #f9f9f9; }}
                .security-box {{ background-color: #e9e9e9; padding: 20px; border-radius: 5px; margin: 20px 0; }}
                .passcode {{ font-size: 28px; font-weight: bold; color: #4CAF50; letter-spacing: 2px; }}
                .button {{ display: inline-block; padding: 12px 24px; background-color: white; color: #4CAF50; 
                            text-decoration: none; border-radius: 5px; font-weight: bold; border: 2px solid #4CAF50; }}
                .warning {{ color: #f44336; font-size: 14px; }}
                .info-box {{ background-color: #fff; padding: 15px; border-left: 4px solid #4CAF50; margin: 15px 0; }}
                .match-badge {{ background-color: #4CAF50; color: white; padding: 3px 8px; border-radius: 12px; 
                            font-size: 12px; display: inline-block; margin-left: 10px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>Request for Quotation</h2>
                    <p>RFX: {data[0]} <span class="match-badge">{data[3]}% Match</span></p>
                </div>
                
                <div class="content">
                    <p>Dear <strong>{data[5] or data[4] or 'Supplier'}</strong>,</p>
                    
                    <p>You have been invited to submit a quotation for the above RFX. Based on your company's 
                    registered products and categories, we've identified the items below as potential matches for your business.</p>
                    
                    <div class="info-box">
                        <h3>📋 RFX Summary</h3>
                        {budget_info}
                        <p><strong>Required Date:</strong> {required_date}</p>
                        <p><strong>Delivery Deadline:</strong> {delivery_deadline}</p>
                    </div>
                    
                    {items_html}
                    
                    <div class="security-box">
                        <h3>🔐 Two-Step Security Access</h3>
                        
                        <p><strong>Step 1:</strong> Click the secure link below to access the quotation portal</p>
                        <p style="text-align: center;">
                            <a href="{access_link}" class="button">Access Quotation Portal</a>
                        </p>
                        
                        <p><strong>Step 2:</strong> Enter your unique passcode when prompted</p>
                        <p style="text-align: center; font-size: 24px; font-weight: bold; color: #4CAF50; letter-spacing: 3px;">
                            {data[2]}
                        </p>
                        
                        <p class="warning"><small>⚠️ This passcode is unique to your company. Do not share it with others.</small></p>
                    </div>
                    
                    <p>In the portal, you will be able to:</p>
                    <ul>
                        <li>Review all items (including those that may not match your products)</li>
                        <li>Submit your quotation with pricing per item (quote only for items you can supply)</li>
                        <li>Specify delivery timelines and warranties</li>
                        <li>Provide your payment terms</li>
                    </ul>
                    
                    <p><strong>⏰ This quotation link will expire on {expiry_str}.</strong></p>
                    
                    <p>If you have any questions regarding this RFX, please don't hesitate to contact us.</p>
                    
                    <p>Best regards,<br>
                    <strong>{self.sender_name}</strong></p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version with filtered items
        text_body = f"""
    Dear {data[5] or data[4] or 'Supplier'},

    You have been invited to submit a quotation for RFX {data[0]}. 
    Your company has a {data[3]}% match score for this RFX.

    RFX SUMMARY:
    ------------
    {budget_text_line}
    Required Date: {required_date}
    Delivery Deadline: {delivery_deadline}

    {items_text}

    TWO-STEP SECURITY ACCESS:
    -------------------------
    Step 1: Access the quotation portal using this link:
    {access_link}

    Step 2: Enter your unique passcode when prompted:
    {data[2]}

    ⚠️ IMPORTANT: This passcode is unique to your company. Do not share it.

    In the portal, you will be able to:
    - Review all items (including those that may not match your products)
    - Submit your quotation with pricing per item (quote only for items you can supply)
    - Specify delivery timelines and warranties
    - Provide your payment terms

    ⏰ This quotation link will expire on {expiry_str}.

    If you have any questions regarding this RFX, please don't hesitate to contact us.

    Best regards,
    {self.sender_name}
        """
        
        return {
            "status": "success",
            "to_email": data[6],
            "to_name": data[4],  # company_name
            "subject": f"📋 Request for Quotation: {data[0]} - {data[3]}% Match for Your Products",
            "html_body": html_body,
            "text_body": text_body,
            "rfq_id": data[0],
            "mapping_id": mapping_id,
            "access_code": data[1],
            "passcode": data[2],
            "encrypted_code": encrypted_code,
            "access_link": access_link,
            "expiry_date": expiry_str,
            "match_score": data[3],
            "matching_items_count": len(matching_items),
            "total_items_count": len(all_items)
        }
    
    def send_email(self, to_email: str, subject: str, html_body: str, text_body: str = None) -> bool:
        """
        Send email using SMTP configuration
        Returns True if successful, False otherwise
        """
        if not all([self.smtp_host, self.smtp_port, self.smtp_user, self.smtp_pass]):
            logger.error("Email configuration incomplete. Check SMTP_* environment variables.")
            return False
        
        try:
            msg = EmailMessage()
            msg["From"] = formataddr((self.sender_name, self.smtp_user))
            msg["To"] = to_email
            msg["Subject"] = subject
            
            # Set plain text version
            if text_body:
                msg.set_content(text_body)
            
            # Add HTML version
            msg.add_alternative(html_body, subtype='html')
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False
    
    def send_rfq_emails(self, rfq_id: str, test_mode: bool = None, base_url: str = None) -> Dict[str, Any]:
        """
        Send RFQ emails to matched suppliers
        
        Args:
            rfq_id: The RFQ ID
            test_mode: If True, just log emails without sending (uses instance default if None)
            base_url: Base URL for supplier portal (uses instance default if None)
        
        Returns:
            Dict with email sending results
        """
        # Use instance defaults if not provided
        if test_mode is None:
            test_mode = self.email_test_mode
        if base_url is None:
            base_url = self.base_url
            
        try:
            # Get pending suppliers for this RFQ
            self.cursor.execute("""
                SELECT rs.mapping_id, s.supplier_id, s.company_name, s.email,
                    rs.match_score
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE rs.rfq_id = ? AND rs.email_sent = 0
                ORDER BY rs.match_score DESC
            """, (rfq_id,))
            
            suppliers = self.cursor.fetchall()
            
            if not suppliers:
                return {
                    "status": "error",
                    "message": "No pending suppliers found for this RFQ"
                }
            
            sent_emails = []
            failed_emails = []
            
            for supplier in suppliers:
                mapping_id = supplier[0]
                
                # Generate email content
                email_content = self.generate_email_content(mapping_id)
                
                if email_content['status'] == 'error':
                    failed_emails.append({
                        "mapping_id": mapping_id,
                        "company": supplier[2],
                        "error": email_content['message']
                    })
                    continue
                
                email_sent = False
                
                if test_mode:
                    # Log in test mode
                    logger.info(f"TEST MODE: Would send email to {supplier[3]} for RFQ {rfq_id}")
                    logger.info(f"Subject: {email_content['subject']}")
                    logger.info(f"Access Link: {email_content['access_link']}")
                    logger.info(f"Passcode: {email_content['passcode']}")
                    
                    # Insert into email_logs (simulated) - STORE FULL EMAIL BODY
                    self.cursor.execute("""
                        INSERT INTO [RFQ].[email_logs]
                        (rfq_id, supplier_id, email_to, email_subject, email_body, 
                        email_type, status, tracking_id, created_at)
                        OUTPUT INSERTED.email_id
                        VALUES (?, ?, ?, ?, ?, 'RFQ', 'SIMULATED', ?, GETDATE())
                    """, (
                        rfq_id, 
                        supplier[1], 
                        supplier[3], 
                        email_content['subject'],
                        email_content['text_body'],  # Store FULL text body, not just preview
                        f"TEST-{secrets.token_hex(4)}"
                    ))
                    
                    email_id = self.cursor.fetchone()[0]
                    email_sent = True
                    
                else:
                    # Send actual email
                    email_sent = self.send_email(
                        to_email=supplier[3],
                        subject=email_content['subject'],
                        html_body=email_content['html_body'],
                        text_body=email_content['text_body']
                    )
                    
                    if email_sent:
                        # Insert into email_logs (actual) - STORE FULL EMAIL BODY
                        self.cursor.execute("""
                            INSERT INTO [RFQ].[email_logs]
                            (rfq_id, supplier_id, email_to, email_subject, email_body, 
                            email_type, status, tracking_id, created_at)
                            OUTPUT INSERTED.email_id
                            VALUES (?, ?, ?, ?, ?, 'RFQ', 'SENT', ?, GETDATE())
                        """, (
                            rfq_id, 
                            supplier[1], 
                            supplier[3], 
                            email_content['subject'],
                            email_content['text_body'],  # Store FULL text body
                            f"SENT-{secrets.token_hex(4)}"
                        ))
                        
                        email_id = self.cursor.fetchone()[0]
                    else:
                        email_id = None
                
                if email_sent:
                    # Update rfq_suppliers
                    self.cursor.execute("""
                        UPDATE [RFQ].[rfq_suppliers]
                        SET email_sent = 1, email_id = ?, status = 'EMAIL_SENT'
                        WHERE mapping_id = ?
                    """, (email_id, mapping_id))
                    
                    sent_emails.append({
                        "mapping_id": mapping_id,
                        "company": supplier[2],
                        "email": supplier[3],
                        "subject": email_content['subject'],
                        "email_id": email_id,
                        "passcode": email_content['passcode'],
                        "access_link": email_content['access_link']
                    })
                else:
                    failed_emails.append({
                        "mapping_id": mapping_id,
                        "company": supplier[2],
                        "email": supplier[3],
                        "error": "Email sending failed"
                    })
            
            self.connection.commit()
            
            return {
                "status": "success",
                "rfq_id": rfq_id,
                "test_mode": test_mode,
                "emails_sent": len(sent_emails),
                "emails_failed": len(failed_emails),
                "sent_details": sent_emails,
                "failed_details": failed_emails,
                "next_steps": "Awaiting supplier responses through the portal"
            }
            
        except Exception as e:
            logger.error(f"Error sending RFQ emails: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def process_rfq_after_confirmation(self, rfq_id: str) -> Dict[str, Any]:
        """
        Complete process after RFQ confirmation:
        1. Find matching suppliers
        2. Send RFQ emails to matches
        
        Returns:
            Dict with complete process results
        """
        result = {
            "rfq_id": rfq_id,
            "matching": None,
            "email_sending": None,
            "timestamp": datetime.now().isoformat()
        }
        
        # Step 1: Find matching suppliers
        matching_result = self.find_matching_suppliers(rfq_id)
        result["matching"] = matching_result
        
        if matching_result["status"] == "success" and matching_result["total_suppliers_found"] > 0:
            # Step 2: Send emails
            email_result = self.send_rfq_emails(rfq_id)
            result["email_sending"] = email_result
            
            # Update RFQ status
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_headers]
                SET status = 'PROCESSING', updated_at = GETDATE()
                WHERE rfq_id = ?
            """, (rfq_id,))
            self.connection.commit()
            
            result["status"] = "success"
            result["message"] = f"RFQ {rfq_id} processed: Found {matching_result['total_suppliers_found']} suppliers, sent {email_result['emails_sent']} emails"
        else:
            result["status"] = "warning"
            result["message"] = f"RFQ {rfq_id} processed but no matching suppliers found"
        
        return result
    
    def get_supplier_by_passcode(self, passcode: str) -> Dict[str, Any]:
        """Get supplier details by passcode (for portal access)"""
        try:
            self.cursor.execute("""
                SELECT rs.mapping_id, rs.rfq_id, rs.passcode, rs.status,
                       s.supplier_id, s.company_name, s.contact_person,
                       h.total_budget, h.currency
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                JOIN [RFQ].[rfq_headers] h ON rs.rfq_id = h.rfq_id
                WHERE rs.passcode = ? AND rs.status != 'EXPIRED'
            """, (passcode,))
            
            row = self.cursor.fetchone()
            if not row:
                return {"status": "error", "message": "Invalid or expired passcode"}
            
            # Update last_viewed
            self.cursor.execute("""
                UPDATE [RFQ].[rfq_suppliers]
                SET last_viewed = GETDATE(), status = 'VIEWED'
                WHERE mapping_id = ?
            """, (row[0],))
            self.connection.commit()
            
            return {
                "status": "success",
                "mapping_id": row[0],
                "rfq_id": row[1],
                "passcode": row[2],
                "supplier_id": row[4],
                "company_name": row[5],
                "contact_person": row[6],
                "budget": float(row[7]) if row[7] else None,
                "currency": row[8]
            }
            
        except Exception as e:
            logger.error(f"Error validating passcode: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    def resend_rfq_email(self, mapping_id: int) -> Dict[str, Any]:
        """
        Resend RFQ email to a specific supplier
        
        Args:
            mapping_id: The rfq_suppliers mapping ID
        
        Returns:
            Dict with resend results
        """
        try:
            # Get supplier details
            self.cursor.execute("""
                SELECT rs.rfq_id, s.supplier_id, s.company_name, s.email,
                       rs.email_sent, rs.status
                FROM [RFQ].[rfq_suppliers] rs
                JOIN [RFQ].[suppliers] s ON rs.supplier_id = s.supplier_id
                WHERE rs.mapping_id = ?
            """, (mapping_id,))
            
            row = self.cursor.fetchone()
            if not row:
                return {
                    "status": "error",
                    "message": f"No mapping found for ID {mapping_id}"
                }
            
            # Generate email content
            email_content = self.generate_email_content(mapping_id)
            
            if email_content['status'] == 'error':
                return email_content
            
            # Send email
            email_sent = self.send_email(
                to_email=row[3],
                subject=email_content['subject'],
                html_body=email_content['html_body'],
                text_body=email_content['text_body']
            )
            
            if email_sent:
                # Insert into email_logs
                self.cursor.execute("""
                    INSERT INTO [RFQ].[email_logs]
                    (rfq_id, supplier_id, email_to, email_subject, email_type, 
                     status, tracking_id, created_at)
                    OUTPUT INSERTED.email_id
                    VALUES (?, ?, ?, ?, 'RFQ', 'RESENT', ?, GETDATE())
                """, (
                    row[0], 
                    row[1], 
                    row[3], 
                    email_content['subject'],
                    f"RESENT-{secrets.token_hex(4)}"
                ))
                
                email_id = self.cursor.fetchone()[0]
                
                # Update rfq_suppliers
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET email_sent = 1, email_id = ?, status = 'EMAIL_SENT'
                    WHERE mapping_id = ?
                """, (email_id, mapping_id))
                
                self.connection.commit()
                
                return {
                    "status": "success",
                    "message": f"Email resent successfully to {row[2]}",
                    "mapping_id": mapping_id,
                    "email_id": email_id,
                    "access_link": email_content['access_link']
                }
            else:
                return {
                    "status": "error",
                    "message": "Failed to send email"
                }
                
        except Exception as e:
            logger.error(f"Error resending email: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def validate_passcode_for_mapping(self, mapping_id: int, passcode: str) -> bool:
        """
        Validate passcode for a specific mapping
        """
        try:
            self.cursor.execute("""
                SELECT COUNT(*) FROM [RFQ].[rfq_suppliers]
                WHERE mapping_id = ? AND passcode = ? AND status != 'EXPIRED'
            """, (mapping_id, passcode))
            
            count = self.cursor.fetchone()[0]
            
            if count > 0:
                # Update last_viewed timestamp
                self.cursor.execute("""
                    UPDATE [RFQ].[rfq_suppliers]
                    SET last_viewed = GETDATE()
                    WHERE mapping_id = ? AND status = 'PENDING'
                """, (mapping_id,))
                
                self.connection.commit()
                logger.info(f"Successful passcode validation for mapping_id: {mapping_id}")
                return True
            
            logger.warning(f"Failed passcode validation attempt for mapping_id: {mapping_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error validating passcode: {str(e)}")
            return False